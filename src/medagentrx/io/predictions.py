# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Prediction files: one per model version, all on the same locked test set.

Columns: ``row_id`` (unique string), ``y_true`` (0 or 1), ``y_score`` (a
probability in [0, 1]) and any subgroup columns named in the plan. Files are
joined on ``row_id``.

Score files for deployment QC use the same format without labels: ``row_id``
and ``y_score`` only (``load_scores``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

import numpy as np
import numpy.typing as npt

from medagentrx.errors import InputError
from medagentrx.io.limits import Limits
from medagentrx.io.tables import Cell, RawTable, read_table

ROW_ID = "row_id"
Y_TRUE = "y_true"
Y_SCORE = "y_score"
FORBIDDEN_ID_CHARACTERS = ("\t", "\n", "\r")


@dataclass(frozen=True)
class Predictions:
    """Validated predictions of one model version. Arrays are read-only.

    Attributes:
        source: The path as given by the user.
        row_id: Row identifiers, unique.
        y_true: Outcome labels as int8 zeros and ones.
        y_score: Predicted probabilities as float64.
        subgroups: Subgroup column name to string labels per row.
    """

    source: str
    row_id: npt.NDArray[np.str_]
    y_true: npt.NDArray[np.int8]
    y_score: npt.NDArray[np.float64]
    subgroups: Mapping[str, npt.NDArray[np.str_]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @property
    def n(self) -> int:
        """Number of rows."""
        return int(self.row_id.shape[0])


def load_predictions(
    path: str | Path,
    *,
    subgroup_columns: Sequence[str] = (),
    limits: Limits | None = None,
    base: Path | None = None,
) -> Predictions:
    """Load and validate a prediction file.

    Raises:
        InputError: If a column is missing, a value is invalid, or a row id repeats.
    """
    table = read_table(
        path, required=[ROW_ID, Y_TRUE, Y_SCORE, *subgroup_columns], limits=limits, base=base
    )
    if table.n_rows == 0:
        raise InputError(f"{table.source}: no data rows")
    row_id = _row_ids(table, ROW_ID)
    y_true = _labels(table, row_id)
    y_score = _scores(table, row_id)
    subgroups = {name: _strings(table, name, row_id) for name in subgroup_columns}
    return Predictions(
        source=table.source,
        row_id=_frozen(np.array(row_id, dtype=np.str_)),
        y_true=_frozen(np.array(y_true, dtype=np.int8)),
        y_score=_frozen(np.array(y_score, dtype=np.float64)),
        subgroups=MappingProxyType(
            {name: _frozen(np.array(values, dtype=np.str_)) for name, values in subgroups.items()}
        ),
    )


@dataclass(frozen=True)
class Scores:
    """Validated scores without labels, as produced on the QC control set.

    Attributes:
        source: The path as given by the user.
        row_id: Row identifiers, unique.
        y_score: Scores as float64, in [0, 1].
    """

    source: str
    row_id: npt.NDArray[np.str_]
    y_score: npt.NDArray[np.float64]

    @property
    def n(self) -> int:
        """Number of rows."""
        return int(self.row_id.shape[0])

    def by_id(self) -> dict[str, float]:
        """Score of each row id."""
        return dict(zip(self.row_id.tolist(), self.y_score.tolist(), strict=True))


def load_scores(
    path: str | Path, *, limits: Limits | None = None, base: Path | None = None
) -> Scores:
    """Load and validate a score file: ``row_id`` and ``y_score``, no labels.

    Raises:
        InputError: If a column is missing, a value is invalid, or a row id repeats.
    """
    table = read_table(path, required=[ROW_ID, Y_SCORE], limits=limits, base=base)
    if table.n_rows == 0:
        raise InputError(f"{table.source}: no data rows")
    row_id = _row_ids(table, ROW_ID)
    y_score = _scores(table, row_id)
    return Scores(
        source=table.source,
        row_id=_frozen(np.array(row_id, dtype=np.str_)),
        y_score=_frozen(np.array(y_score, dtype=np.float64)),
    )


def load_row_ids(
    path: str | Path, *, limits: Limits | None = None, base: Path | None = None
) -> list[str]:
    """The ``row_id`` column of any table, such as the raw QC control inputs.

    Raises:
        InputError: If the column is missing, empty, or repeats an id.
    """
    table = read_table(path, required=[ROW_ID], limits=limits, base=base)
    if table.n_rows == 0:
        raise InputError(f"{table.source}: no data rows")
    return _row_ids(table, ROW_ID)


_T = TypeVar("_T", bound=np.generic)


def _frozen(array: npt.NDArray[_T]) -> npt.NDArray[_T]:
    array.flags.writeable = False
    return array


def _where(table: RawTable, index: int, row_id: Sequence[str] | None = None) -> str:
    label = f"row {index + 1}"
    if row_id is not None:
        label += f" (row_id {row_id[index]!r})"
    return f"{table.source}: {label}"


def _row_ids(table: RawTable, column: str) -> list[str]:
    values = table.columns[column]
    ids: list[str] = []
    seen: set[str] = set()
    for i, value in enumerate(values):
        if not isinstance(value, str) or not value:
            raise InputError(f"{_where(table, i)}: {column} must be a non-empty string")
        if any(ch in value for ch in FORBIDDEN_ID_CHARACTERS):
            raise InputError(f"{_where(table, i)}: {column} must not contain tabs or line breaks")
        if value in seen:
            raise InputError(f"{_where(table, i)}: duplicate {column} {value!r}")
        seen.add(value)
        ids.append(value)
    return ids


def _labels(table: RawTable, row_id: Sequence[str]) -> list[int]:
    labels: list[int] = []
    for i, value in enumerate(table.columns[Y_TRUE]):
        label = _as_label(value)
        if label is None:
            raise InputError(f"{_where(table, i, row_id)}: {Y_TRUE} must be 0 or 1, got {value!r}")
        labels.append(label)
    return labels


def _as_label(value: Cell) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return int(value.strip())
    return None


def _scores(table: RawTable, row_id: Sequence[str]) -> list[float]:
    scores: list[float] = []
    for i, value in enumerate(table.columns[Y_SCORE]):
        score = _as_float(value)
        if score is None or not math.isfinite(score):
            raise InputError(
                f"{_where(table, i, row_id)}: {Y_SCORE} must be a finite number, got {value!r}"
            )
        if not 0.0 <= score <= 1.0:
            raise InputError(f"{_where(table, i, row_id)}: {Y_SCORE} {score} is outside [0, 1]")
        scores.append(score)
    return scores


def _as_float(value: Cell) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return None


def _strings(table: RawTable, column: str, row_id: Sequence[str]) -> list[str]:
    out: list[str] = []
    for i, value in enumerate(table.columns[column]):
        if value is None or value == "":
            raise InputError(f"{_where(table, i, row_id)}: {column} is missing")
        out.append(value if isinstance(value, str) else str(value))
    return out


@dataclass(frozen=True)
class RowMismatch:
    """How the rows of two prediction files differ.

    Attributes:
        missing: Row ids in the reference but not in the other file.
        extra: Row ids in the other file but not in the reference.
        label_changed: Row ids whose ``y_true`` differs.
    """

    missing: tuple[str, ...]
    extra: tuple[str, ...]
    label_changed: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.missing or self.extra or self.label_changed)

    def describe(self, limit: int = 5) -> list[str]:
        """Return one line per kind of mismatch, showing at most ``limit`` ids."""
        lines = []
        for name, ids in (
            ("missing rows", self.missing),
            ("extra rows", self.extra),
            ("changed labels", self.label_changed),
        ):
            if ids:
                shown = ", ".join(repr(i) for i in ids[:limit])
                more = f" and {len(ids) - limit} more" if len(ids) > limit else ""
                lines.append(f"{len(ids)} {name}: {shown}{more}")
        return lines


class RowMismatchError(InputError):
    """Two prediction files do not describe the same rows and labels."""

    def __init__(self, summary: str, mismatch: RowMismatch) -> None:
        self.mismatch = mismatch
        super().__init__(summary, mismatch.describe())


def compare_rows(reference: Predictions, other: Predictions) -> RowMismatch:
    """Compare the rows and labels of two prediction files."""
    ref_labels = dict(zip(reference.row_id.tolist(), reference.y_true.tolist(), strict=True))
    other_labels = dict(zip(other.row_id.tolist(), other.y_true.tolist(), strict=True))
    missing = tuple(sorted(set(ref_labels) - set(other_labels)))
    extra = tuple(sorted(set(other_labels) - set(ref_labels)))
    changed = tuple(
        sorted(
            rid
            for rid in set(ref_labels) & set(other_labels)
            if ref_labels[rid] != other_labels[rid]
        )
    )
    return RowMismatch(missing=missing, extra=extra, label_changed=changed)


def align(reference: Predictions, other: Predictions) -> Predictions:
    """Return ``other`` reordered to the row order of ``reference``.

    Raises:
        RowMismatchError: If the files differ in rows or labels.
    """
    mismatch = compare_rows(reference, other)
    if mismatch:
        raise RowMismatchError(
            f"{other.source}: rows or labels differ from {reference.source}", mismatch
        )
    position = {rid: i for i, rid in enumerate(other.row_id.tolist())}
    order = np.array([position[rid] for rid in reference.row_id.tolist()], dtype=np.intp)
    return Predictions(
        source=other.source,
        row_id=_frozen(other.row_id[order]),
        y_true=_frozen(other.y_true[order]),
        y_score=_frozen(other.y_score[order]),
        subgroups=MappingProxyType(
            {name: _frozen(values[order]) for name, values in other.subgroups.items()}
        ),
    )

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Training data manifest: one row per training example.

Columns: ``row_id``, ``patient_id`` and every field named in the plan's
``training_inclusion``. Any other column is kept as an optional feature,
used only for population shift warnings.

CSV columns are typed per column: integers if every value is an integer,
else numbers if every value is a number, else text. Empty cells are missing
values. Dates stay ``YYYY-MM-DD`` text, which sorts in date order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from medagentrx.errors import InputError
from medagentrx.io.limits import Limits
from medagentrx.io.predictions import ROW_ID
from medagentrx.io.tables import Cell, read_table

PATIENT_ID = "patient_id"

Value = str | int | float | bool | None


@dataclass(frozen=True)
class Manifest:
    """A validated training manifest.

    Attributes:
        source: The path as given by the user.
        row_id: Unique row identifiers.
        patient_id: Patient identifier per row.
        columns: Every other column, typed, with ``None`` for missing values.
    """

    source: str
    row_id: tuple[str, ...]
    patient_id: tuple[str, ...]
    columns: Mapping[str, tuple[Value, ...]]

    @property
    def n(self) -> int:
        """Number of rows."""
        return len(self.row_id)


def load_manifest(
    path: str | Path,
    *,
    required_fields: Sequence[str] = (),
    limits: Limits | None = None,
    base: Path | None = None,
) -> Manifest:
    """Load and validate a training manifest.

    Args:
        path: CSV or Parquet file.
        required_fields: Columns the plan's conditions read.
        limits: Size limits.
        base: Directory symlinks may point into.

    Raises:
        InputError: If a column is missing or an identifier is invalid.
    """
    table = read_table(
        path,
        required=[ROW_ID, PATIENT_ID, *required_fields],
        all_columns=True,
        limits=limits,
        base=base,
    )
    if table.n_rows == 0:
        raise InputError(f"{table.source}: no data rows")
    row_id = _identifiers(table.source, ROW_ID, table.columns[ROW_ID], unique=True)
    patient_id = _identifiers(table.source, PATIENT_ID, table.columns[PATIENT_ID], unique=False)
    columns = {
        name: tuple(_typed(values) if table.from_csv else values)
        for name, values in table.columns.items()
        if name not in (ROW_ID, PATIENT_ID)
    }
    for name, values in columns.items():
        for i, value in enumerate(values):
            if isinstance(value, float) and not math.isfinite(value):
                raise InputError(f"{table.source}: row {i + 1}: {name} is {value}, not a number")
    return Manifest(
        source=table.source,
        row_id=tuple(row_id),
        patient_id=tuple(patient_id),
        columns=MappingProxyType(columns),
    )


def _identifiers(source: str, column: str, values: list[Cell], *, unique: bool) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for i, value in enumerate(values):
        if value is None or value == "":
            raise InputError(f"{source}: row {i + 1}: {column} is missing")
        text = value if isinstance(value, str) else str(value)
        if unique and text in seen:
            raise InputError(f"{source}: row {i + 1}: duplicate {column} {text!r}")
        seen.add(text)
        out.append(text)
    return out


def _typed(values: list[Cell]) -> list[Value]:
    present = [v for v in values if v not in (None, "")]
    for convert in (int, float):
        try:
            converted = [convert(v) for v in present]
        except ValueError:
            continue
        lookup = iter(converted)
        return [None if v in (None, "") else next(lookup) for v in values]
    return [None if v in (None, "") else v for v in values]

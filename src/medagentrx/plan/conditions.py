# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Helpers over the structured condition tree of a plan.

``evaluate`` tests one row. ``evaluate_columns`` tests a whole table at once
with numpy and gives the same answer for every row; DATA-003 uses it so that
manifests with millions of rows stay fast.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from medagentrx.plan.models import (
    AllCondition,
    AnyCondition,
    Condition,
    LeafCondition,
    NotCondition,
)


def condition_fields(condition: Condition) -> list[str]:
    """Return the field names a condition reads, in first-use order."""
    found: dict[str, None] = {}
    _collect(condition, found)
    return list(found)


def _collect(condition: Condition, found: dict[str, None]) -> None:
    if isinstance(condition, LeafCondition):
        found.setdefault(condition.field)
    elif isinstance(condition, AllCondition):
        for inner in condition.all_:
            _collect(inner, found)
    elif isinstance(condition, AnyCondition):
        for inner in condition.any_:
            _collect(inner, found)
    elif isinstance(condition, NotCondition):  # pragma: no branch
        _collect(condition.not_, found)


Row = Mapping[str, object]


def evaluate(condition: Condition, row: Row) -> bool:
    """Return whether ``row`` meets ``condition``.

    A missing value (``None``) meets only ``is_null``. Values of types that
    cannot be compared, such as a number and a string, never meet a
    comparison. Strings compare by code point, so ``YYYY-MM-DD`` dates
    compare in date order.
    """
    if isinstance(condition, AllCondition):
        return all(evaluate(inner, row) for inner in condition.all_)
    if isinstance(condition, AnyCondition):
        return any(evaluate(inner, row) for inner in condition.any_)
    if isinstance(condition, NotCondition):
        return not evaluate(condition.not_, row)
    return _leaf(condition, row.get(condition.field))


def _kind(value: object) -> str | None:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _same_kind(a: object, b: object) -> bool:
    kind = _kind(a)
    return kind is not None and kind == _kind(b)


def _leaf(leaf: LeafCondition, value: object) -> bool:
    op, target = leaf.op, leaf.value
    if op == "is_null":
        return value is None
    if op == "not_null":
        return value is not None
    if value is None:
        return False
    if op in ("in", "not_in"):
        assert isinstance(target, list)  # noqa: S101  # guaranteed by the model
        found = any(_same_kind(value, t) and value == t for t in target)
        return found if op == "in" else not found
    if op == "between":
        assert isinstance(target, list)  # noqa: S101  # guaranteed by the model
        low, high = target
        if not (_same_kind(value, low) and _same_kind(value, high)):
            return False
        return bool(low <= value <= high)  # type: ignore[operator]
    if not _same_kind(value, target):
        return op == "ne"
    if op == "eq":
        return value == target
    if op == "ne":
        return value != target
    ordered: dict[str, bool] = {
        "lt": value < target,  # type: ignore[operator]
        "le": value <= target,  # type: ignore[operator]
        "gt": value > target,  # type: ignore[operator]
        "ge": value >= target,  # type: ignore[operator]
    }
    return ordered[op]


Mask = npt.NDArray[np.bool_]
_EXACT_FLOAT_INT = 2**53


@dataclass(frozen=True)
class _Column:
    """One column, typed for vectorised comparison.

    ``kind`` is None when the column mixes kinds, or holds integers too large
    for exact comparison with floats; its leaves then fall back to ``_leaf``.
    """

    kind: str | None
    values: npt.NDArray[np.generic]
    null: Mask
    raw: Sequence[object]


_KINDS_BY_TYPES: dict[frozenset[type], str] = {
    frozenset({int}): "number",
    frozenset({float}): "number",
    frozenset({int, float}): "number",
    frozenset({str}): "string",
    frozenset({bool}): "bool",
    frozenset(): "empty",
}
_FILL: dict[str, tuple[object, type]] = {
    "number": (0.0, np.float64),
    "string": ("", np.str_),
    "bool": (False, np.bool_),
}


def _column(raw: Sequence[object]) -> _Column:
    cells = np.empty(len(raw), dtype=object)
    cells[:] = list(raw)
    null: Mask = np.equal(cells, None)
    kind = _KINDS_BY_TYPES.get(frozenset(map(type, raw)) - {type(None)})
    if kind == "number":
        try:
            magnitude = np.abs(cells[~null].astype(np.float64))
        except OverflowError:
            magnitude = np.array([np.inf])
        if np.any(magnitude >= _EXACT_FLOAT_INT):
            kind = None  # float64 would round integers this large
    if kind in _FILL:
        fill, dtype = _FILL[kind]
        cells[null] = fill
        values: npt.NDArray[np.generic] = cells.astype(dtype)
    else:
        values = np.zeros(len(raw), dtype=bool)
    return _Column(kind, values, null, raw)


def evaluate_columns(
    condition: Condition, columns: Mapping[str, Sequence[object]], n_rows: int
) -> Mask:
    """Whether each row meets ``condition``, for a table given as columns.

    Agrees with ``evaluate`` on every row. A field absent from ``columns`` is
    missing in every row.
    """
    cache: dict[str, _Column] = {}

    def column(name: str) -> _Column:
        if name not in cache:
            cache[name] = _column(columns.get(name, (None,) * n_rows))
        return cache[name]

    def walk(node: Condition) -> Mask:
        if isinstance(node, AllCondition):
            out = np.ones(n_rows, dtype=bool)
            for inner in node.all_:
                out &= walk(inner)
            return out
        if isinstance(node, AnyCondition):
            out = np.zeros(n_rows, dtype=bool)
            for inner in node.any_:
                out |= walk(inner)
            return out
        if isinstance(node, NotCondition):
            return ~walk(node.not_)
        return _leaf_mask(node, column(node.field))

    return walk(condition)


def _leaf_mask(leaf: LeafCondition, col: _Column) -> Mask:
    op, target = leaf.op, leaf.value
    present = ~col.null
    if op == "is_null":
        return col.null.copy()
    if op == "not_null":
        return present
    if col.kind is None:
        return np.fromiter((_leaf(leaf, v) for v in col.raw), dtype=bool, count=len(col.raw))
    if col.kind == "empty":
        return np.zeros(len(col.raw), dtype=bool)
    v = col.values
    nowhere = np.zeros(len(v), dtype=bool)
    if op in ("in", "not_in"):
        assert isinstance(target, list)  # noqa: S101  # guaranteed by the model
        matching = [t for t in target if _kind(t) == col.kind]
        found = present & np.isin(v, np.array(matching, dtype=v.dtype)) if matching else nowhere
        return found if op == "in" else present & ~found
    if op == "between":
        assert isinstance(target, list)  # noqa: S101  # guaranteed by the model
        low, high = target
        if _kind(low) != col.kind or _kind(high) != col.kind:
            return nowhere
        inside: Mask = present & np.greater_equal(v, low) & np.less_equal(v, high)
        return inside
    if _kind(target) != col.kind:
        return present if op == "ne" else nowhere
    compare = {
        "eq": np.equal,
        "ne": np.not_equal,
        "lt": np.less,
        "le": np.less_equal,
        "gt": np.greater,
        "ge": np.greater_equal,
    }[op]
    result: Mask = present & compare(v, target)
    return result

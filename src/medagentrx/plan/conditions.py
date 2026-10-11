# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Helpers over the structured condition tree of a plan."""

from __future__ import annotations

from collections.abc import Mapping

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

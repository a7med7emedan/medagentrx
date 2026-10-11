# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Helpers over the structured condition tree of a plan."""

from __future__ import annotations

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

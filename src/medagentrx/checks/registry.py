# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Check catalogue: identifiers, families, severities and cross-references.

Each check is a function of the evaluation context that returns one
``Finding``. The registry keeps them in catalogue order. The documentation
page of checks is produced from this registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from medagentrx.checks.context import Context


class Family(StrEnum):
    """Check families."""

    PLAN = "PLAN"
    DATA = "DATA"
    PERF = "PERF"
    LIFE = "LIFE"
    DOC = "DOC"


class Breaks(StrEnum):
    """What a failed check does to the verdict."""

    OUTSIDE_PLAN = "OUTSIDE_PLAN"
    FAILED = "FAILED"
    WARNING = "WARNING"


class Status(StrEnum):
    """Outcome of one check."""

    PASS = "pass"  # noqa: S105  # a check outcome, not a password
    FAIL = "fail"
    WARN = "warn"
    NOT_APPLICABLE = "not_applicable"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Finding:
    """Result of one check.

    Attributes:
        check_id: Catalogue identifier, for example ``PERF-001``.
        status: Outcome.
        message: One-line explanation for people.
        details: Numbers and lists behind the outcome, JSON-compatible.
    """

    check_id: str
    status: Status
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def spec(self) -> CheckSpec:
        """Catalogue entry of this check."""
        return REGISTRY[self.check_id]


CheckFunction = Callable[["Context"], Finding]


@dataclass(frozen=True)
class CheckSpec:
    """Catalogue entry of one check."""

    check_id: str
    family: Family
    title: str
    breaks: Breaks
    cross_reference: str
    run: CheckFunction


REGISTRY: dict[str, CheckSpec] = {}


def check(
    check_id: str, family: Family, title: str, breaks: Breaks, cross_reference: str
) -> Callable[[CheckFunction], CheckFunction]:
    """Register a check function under ``check_id``."""

    def register(function: CheckFunction) -> CheckFunction:
        if check_id in REGISTRY:
            raise ValueError(f"duplicate check id {check_id}")
        REGISTRY[check_id] = CheckSpec(check_id, family, title, breaks, cross_reference, function)
        return function

    return register


def catalogue() -> list[CheckSpec]:
    """All checks in catalogue order."""
    from medagentrx import checks as _checks  # noqa: F401  # registers every family

    order = {family: i for i, family in enumerate(Family)}
    return sorted(REGISTRY.values(), key=lambda s: (order[s.family], s.check_id))

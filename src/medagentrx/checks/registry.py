# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Check catalogue: identifiers, families, severities and cross-references.

Each check is a function of a context that returns one ``Finding``. The
PLAN, DATA, PERF, LIFE and DOC families judge a candidate update; the LIVE
family judges a deployment QC run of the live system and takes a QC context.
The registry keeps them in catalogue order. The documentation page of checks
is produced from this registry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar


class Family(StrEnum):
    """Check families."""

    PLAN = "PLAN"
    DATA = "DATA"
    PERF = "PERF"
    LIFE = "LIFE"
    DOC = "DOC"
    LIVE = "LIVE"


UPDATE_FAMILIES = (Family.PLAN, Family.DATA, Family.PERF, Family.LIFE, Family.DOC)
"""Families that judge a candidate update."""
QC_FAMILIES = (Family.LIVE,)
"""Families that judge a deployment QC run."""


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


CheckFunction = Callable[[Any], Finding]
"""A check: the update context (PLAN to DOC) or the QC context (LIVE) to one finding."""
_F = TypeVar("_F", bound=Callable[..., Finding])


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
) -> Callable[[_F], _F]:
    """Register a check function under ``check_id``."""

    def register(function: _F) -> _F:
        if check_id in REGISTRY:
            raise ValueError(f"duplicate check id {check_id}")
        REGISTRY[check_id] = CheckSpec(check_id, family, title, breaks, cross_reference, function)
        return function

    return register


def catalogue(families: Iterable[Family] | None = None) -> list[CheckSpec]:
    """Checks in catalogue order, all of them or only those of ``families``."""
    from medagentrx import checks as _checks  # noqa: F401  # registers every family

    chosen = set(Family if families is None else families)
    order = {family: i for i, family in enumerate(Family)}
    specs = [s for s in REGISTRY.values() if s.family in chosen]
    return sorted(specs, key=lambda s: (order[s.family], s.check_id))

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""What earlier evaluations under a plan have used up.

The decision ledger is the source of this summary. The engine reads it to
enforce the plan's budgets: looks at the locked test set, released updates,
release frequency and alpha.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from medagentrx.stats.alpha import AlphaState


@dataclass(frozen=True)
class Release:
    """A version and when it was accepted or put into service."""

    version: str
    at: dt.datetime


@dataclass(frozen=True)
class History:
    """Budgets used by earlier evaluations.

    Attributes:
        plan_id: Plan of the first ledger entry, or None for an empty ledger.
        plan_revision: Revision of that plan.
        plan_fingerprint: Fingerprint of that plan.
        looks_used: Evaluations that touched the locked test set.
        releases: Accepted updates, oldest first. The plan's update count and
            frequency limits count these, whether or not the version was put into
            service, so an acceptance cannot be held back to dodge a limit.
        alpha: Alpha state after the last formal evaluation, or None if none yet.
        entries: Number of ledger entries this summary was read from.
        released_predictions: SHA-256 of the candidate prediction file of each
            accepted version, by version.
        deployed: Accepted versions recorded as put into service, oldest first.
        card_versions: Accepted versions whose model card update was recorded.
    """

    plan_id: str | None = None
    plan_revision: int | None = None
    plan_fingerprint: str | None = None
    looks_used: int = 0
    releases: tuple[Release, ...] = field(default_factory=tuple)
    alpha: AlphaState | None = None
    entries: int = 0
    released_predictions: dict[str, str] = field(default_factory=dict)
    deployed: tuple[Release, ...] = field(default_factory=tuple)
    card_versions: tuple[str, ...] = field(default_factory=tuple)

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""PLAN checks: is this update of a kind the plan allows at all?"""

from __future__ import annotations

import datetime as dt

from medagentrx.checks.context import Context
from medagentrx.checks.registry import Breaks, Family, Finding, Status, check


@check(
    "PLAN-001",
    Family.PLAN,
    "Plan is valid and unchanged since the ledger began",
    Breaks.OUTSIDE_PLAN,
    "A change to a PCCP needs a new submission",
)
def plan_unchanged(ctx: Context) -> Finding:
    """The plan validated on loading; here it must match the plan the ledger started with."""
    history = ctx.history
    header = ctx.plan.plan
    details = {
        "plan_id": header.id,
        "revision": header.revision,
        "plan_fingerprint": ctx.plan_fingerprint,
        "ledger_revision": history.plan_revision,
        "ledger_plan_fingerprint": history.plan_fingerprint,
    }
    if history.plan_fingerprint is None:
        return Finding(
            "PLAN-001", Status.PASS, "Plan is valid; this evaluation starts the ledger", details
        )
    if history.plan_id != header.id or history.plan_revision != header.revision:
        return Finding(
            "PLAN-001",
            Status.FAIL,
            f"Ledger was started under {history.plan_id} revision {history.plan_revision}, "
            f"not {header.id} revision {header.revision}",
            details,
        )
    if history.plan_fingerprint != ctx.plan_fingerprint:
        return Finding(
            "PLAN-001",
            Status.FAIL,
            f"Plan content changed without a new revision (still revision {header.revision})",
            details,
        )
    return Finding("PLAN-001", Status.PASS, "Plan is valid and unchanged", details)


@check(
    "PLAN-002",
    Family.PLAN,
    "Modification is listed in the plan",
    Breaks.OUTSIDE_PLAN,
    "FDA Description of Modifications",
)
def modification_listed(ctx: Context) -> Finding:
    """The candidate's modification_id must name a plan modification."""
    listed = [m.id for m in ctx.plan.modifications]
    wanted = ctx.meta.modification_id
    details = {"modification_id": wanted, "allowed": listed}
    if wanted not in listed:
        return Finding(
            "PLAN-002",
            Status.FAIL,
            f"Modification {wanted!r} is not in the plan (allowed: {', '.join(listed)})",
            details,
        )
    return Finding("PLAN-002", Status.PASS, f"Modification {wanted} is in the plan", details)


@check(
    "PLAN-003",
    Family.PLAN,
    "Intended use is unchanged",
    Breaks.OUTSIDE_PLAN,
    "Focused and bounded principle; AI Act substantial modification",
)
def intended_use_unchanged(ctx: Context) -> Finding:
    """The candidate's intended-use hash must equal the plan's."""
    planned = ctx.plan.plan.intended_use_sha256
    actual = ctx.meta.intended_use_sha256
    details = {"plan": planned, "candidate": actual}
    if actual != planned:
        return Finding(
            "PLAN-003", Status.FAIL, "Intended-use statement differs from the plan", details
        )
    return Finding("PLAN-003", Status.PASS, "Intended-use statement matches the plan", details)


def period_start(at: dt.datetime, period: str) -> dt.datetime:
    """Start of the calendar month, quarter or year containing ``at``."""
    if period == "month":
        month = at.month
    elif period == "quarter":
        month = 3 * ((at.month - 1) // 3) + 1
    else:
        month = 1
    return at.replace(month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


@check(
    "PLAN-004",
    Family.PLAN,
    "Update count and frequency are within the plan",
    Breaks.OUTSIDE_PLAN,
    "FDA Description of Modifications, frequency",
)
def update_budget(ctx: Context) -> Finding:
    """Released updates so far must leave room for one more, overall and this period."""
    releases = ctx.history.releases
    frequency = ctx.plan.update_frequency
    start = period_start(ctx.now, frequency.max_per)
    in_period = [r for r in releases if r.at >= start]
    details = {
        "released": len(releases),
        "max_updates": ctx.plan.max_updates,
        "period": frequency.max_per,
        "period_start": start.isoformat(),
        "released_this_period": len(in_period),
        "max_per_period": frequency.count,
    }
    if len(releases) >= ctx.plan.max_updates:
        return Finding(
            "PLAN-004",
            Status.FAIL,
            f"All {ctx.plan.max_updates} updates allowed by the plan have been released",
            details,
        )
    if len(in_period) >= frequency.count:
        return Finding(
            "PLAN-004",
            Status.FAIL,
            f"{len(in_period)} update(s) already released this {frequency.max_per}; "
            f"the plan allows {frequency.count}",
            details,
        )
    return Finding(
        "PLAN-004",
        Status.PASS,
        f"Update {len(releases) + 1} of {ctx.plan.max_updates}, within the "
        f"{frequency.max_per}ly limit",
        details,
    )

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""LIFE checks: does the update keep the model inside the plan over its lifetime?"""

from __future__ import annotations

import dataclasses

from medagentrx.checks.context import Context
from medagentrx.checks.perf_checks import skipped
from medagentrx.checks.registry import Breaks, Family, Finding, Status, check
from medagentrx.stats.delong import paired_test_from


@check(
    "LIFE-001",
    Family.LIFE,
    "Cumulative drift against the anchor is within budget (bio-creep guard)",
    Breaks.FAILED,
    "Feng et al. 2021, Biometrics",
)
def cumulative_drift(ctx: Context) -> Finding:
    """The lower bound of AUC_candidate - AUC_anchor must stay at or above -max_drop."""
    if (skip := skipped("LIFE-001", ctx)) is not None:
        return skip
    guard = ctx.plan.performance.cumulative_drift
    test = paired_test_from(
        ctx.aucs, 0, 2, margin=guard.max_drop_vs_anchor, alpha=ctx.require_alpha()
    )
    details = {"max_drop_vs_anchor": guard.max_drop_vs_anchor, "test": dataclasses.asdict(test)}
    text = (
        f"AUROC vs anchor {test.delta:+.4f}, lower bound {test.ci_lower:+.4f}, "
        f"budget -{guard.max_drop_vs_anchor}"
    )
    if not test.non_inferior:
        return Finding("LIFE-001", Status.FAIL, f"Cumulative drift beyond budget: {text}", details)
    return Finding("LIFE-001", Status.PASS, f"Cumulative drift within budget: {text}", details)


@check(
    "LIFE-002",
    Family.LIFE,
    "Alpha budget is not exhausted",
    Breaks.OUTSIDE_PLAN,
    "Error control across the lifecycle",
)
def alpha_budget(ctx: Context) -> Finding:
    """Some alpha must remain for this evaluation."""
    state = ctx.alpha_state
    details = {
        "method": state.method,
        "alpha_total": state.alpha_total,
        "spent_before": state.spent,
        "evaluations_before": state.updates_tested,
        "alpha_this_evaluation": ctx.alpha,
    }
    if ctx.alpha is None:
        return Finding(
            "LIFE-002",
            Status.FAIL,
            f"Alpha budget exhausted after {state.updates_tested} evaluation(s) "
            f"({state.method}, total {state.alpha_total})",
            details,
        )
    return Finding(
        "LIFE-002",
        Status.PASS,
        f"Testing at alpha {ctx.alpha:.5f} ({state.method}; {state.spent:.5f} of "
        f"{state.alpha_total} spent before)",
        details,
    )

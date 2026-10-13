# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""DOC checks: can the documentation the plan requires be produced?"""

from __future__ import annotations

from medagentrx.checks.context import Context
from medagentrx.checks.perf_checks import skipped
from medagentrx.checks.registry import Breaks, Family, Finding, Status, check
from medagentrx.errors import StatsError
from medagentrx.stats.calibration import calibration
from medagentrx.stats.delong import auc_ci
from medagentrx.stats.metrics import sensitivity, specificity


@check(
    "DOC-001",
    Family.DOC,
    "Model card kept up to date across versions",
    Breaks.FAILED,
    "Update procedures; labelling",
)
def model_card(ctx: Context) -> Finding:
    """When the plan requires a model card update, the card must keep up.

    The previous version, if it was accepted under this plan, must have its
    card update recorded in the ledger (``medagentrx card --ledger``) before
    the next update is checked. Every number this version's section needs must
    also exist. The section itself is written by ``medagentrx card`` from the
    report.
    """
    if not ctx.plan.update_procedures.require_model_card_update:
        return Finding(
            "DOC-001", Status.NOT_APPLICABLE, "The plan does not require a model card update"
        )
    previous = ctx.meta.previous_version
    accepted = {r.version for r in ctx.history.releases}
    if previous in accepted and previous not in ctx.history.card_versions:
        return Finding(
            "DOC-001",
            Status.FAIL,
            f"The model card was not updated for version {previous}, accepted earlier under "
            "this plan; run medagentrx card with --ledger first",
            {"version": ctx.meta.version, "missing_card_for": previous},
        )
    if (skip := skipped("DOC-001", ctx)) is not None:
        return skip
    v = ctx.require_versions().candidate
    threshold = ctx.plan.performance.operating_threshold
    auc = auc_ci(v.y_true, v.y_score)
    try:
        cal = calibration(v.y_true, v.y_score)
    except StatsError as exc:
        return Finding(
            "DOC-001",
            Status.FAIL,
            f"Model card cannot be completed: {exc.summary}",
            {"version": ctx.meta.version},
        )
    card = {
        "version": ctx.meta.version,
        "auroc": auc.auc,
        "auroc_ci": [auc.ci_lower, auc.ci_upper],
        "calibration_slope": cal.slope,
        "calibration_intercept": cal.intercept,
        "brier": cal.brier,
        "threshold": threshold,
        "sensitivity": sensitivity(v.y_true, v.y_score, threshold),
        "specificity": specificity(v.y_true, v.y_score, threshold),
        "n": v.n,
        "n_pos": int(v.y_true.sum()),
    }
    return Finding(
        "DOC-001",
        Status.PASS,
        f"Model card section for version {ctx.meta.version} is complete",
        {"card": card},
    )

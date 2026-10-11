# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""PERF checks: does the update meet the plan's performance criteria?

Every test runs at this evaluation's one-sided level alpha_k. All criteria
must pass (an intersection-union rule), so no correction across criteria is
needed. Intervals are two-sided at 1 - 2 alpha_k.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Literal

from medagentrx.checks.context import Context
from medagentrx.checks.registry import Breaks, Family, Finding, Status, check
from medagentrx.errors import StatsError
from medagentrx.plan.models import NonInferiorityCriterion, WithinCriterion
from medagentrx.stats._common import norm_ppf
from medagentrx.stats.calibration import CalibrationCurve, binned_curve, calibration
from medagentrx.stats.delong import PairedAucTest, auc_ci, delong, paired_test_from
from medagentrx.stats.multiplicity import bonferroni, holm
from medagentrx.stats.net_benefit import decision_curve, net_benefit_difference
from medagentrx.stats.power import analytic_power
from medagentrx.stats.proportions import paired_proportion_test

COMPARATOR_INDEX = {"previous": 1, "anchor": 2}
DISPLAY_LEVEL = 0.95


def skipped(check_id: str, ctx: Context) -> Finding | None:
    """A SKIPPED finding when performance cannot be assessed, else None."""
    blocker = ctx.performance_blocker
    if blocker is None:
        return None
    return Finding(check_id, Status.SKIPPED, f"Not assessed: {blocker}")


def _as_dict(result: object) -> dict[str, Any]:
    return dataclasses.asdict(result)  # type: ignore[call-overload,no-any-return]


def _curve(curve: CalibrationCurve) -> dict[str, list[float]]:
    return {"predicted": curve.predicted.tolist(), "observed": curve.observed.tolist()}


def _criteria(ctx: Context, metrics: tuple[str, ...]) -> list[NonInferiorityCriterion]:
    return [
        c
        for c in ctx.plan.performance.criteria
        if isinstance(c, NonInferiorityCriterion) and c.metric in metrics
    ]


def _auc_test(ctx: Context, comparator: str, margin: float) -> PairedAucTest:
    return paired_test_from(
        ctx.aucs, 0, COMPARATOR_INDEX[comparator], margin=margin, alpha=ctx.require_alpha()
    )


@check(
    "PERF-001",
    Family.PERF,
    "AUROC is non-inferior (paired DeLong)",
    Breaks.FAILED,
    "Performance evaluation protocol",
)
def auroc_non_inferior(ctx: Context) -> Finding:
    """Paired DeLong non-inferiority against each comparator in the plan."""
    if (skip := skipped("PERF-001", ctx)) is not None:
        return skip
    criteria = _criteria(ctx, ("auroc",))
    v = ctx.require_versions()
    display = {
        name: _as_dict(auc_ci(v.candidate.y_true, p.y_score, DISPLAY_LEVEL))
        for name, p in (("candidate", v.candidate), ("previous", v.previous), ("anchor", v.anchor))
    }
    if not criteria:
        return Finding(
            "PERF-001", Status.NOT_APPLICABLE, "No AUROC criterion in the plan", {"auc": display}
        )
    tests = {
        f"vs_{comparator}": _auc_test(ctx, comparator, criterion.margin)
        for criterion in criteria
        for comparator in criterion.vs
    }
    failed = [name for name, t in tests.items() if not t.non_inferior]
    details = {"auc": display, "tests": {k: _as_dict(t) for k, t in tests.items()}}
    summary = "; ".join(
        f"{name.removeprefix('vs_')}: delta {t.delta:+.4f}, lower bound {t.ci_lower:+.4f} "
        f"vs margin -{t.margin}"
        for name, t in tests.items()
    )
    status = Status.FAIL if failed else Status.PASS
    lead = "AUROC is inferior" if failed else "AUROC is non-inferior"
    return Finding("PERF-001", status, f"{lead} ({summary})", details)


@check(
    "PERF-002",
    Family.PERF,
    "Sensitivity and specificity at the operating threshold are non-inferior",
    Breaks.FAILED,
    "Performance evaluation protocol",
)
def threshold_metrics(ctx: Context) -> Finding:
    """Tango paired score intervals at the operating threshold."""
    if (skip := skipped("PERF-002", ctx)) is not None:
        return skip
    criteria = _criteria(ctx, ("sensitivity_at_threshold", "specificity_at_threshold"))
    if not criteria:
        return Finding("PERF-002", Status.NOT_APPLICABLE, "No threshold criterion in the plan")
    v = ctx.require_versions()
    comparators = {"previous": v.previous, "anchor": v.anchor}
    threshold = ctx.plan.performance.operating_threshold
    results = {}
    for criterion in criteria:
        metric: Literal["sensitivity", "specificity"] = (
            "sensitivity" if criterion.metric.startswith("sensitivity") else "specificity"
        )
        for comparator in criterion.vs:
            results[f"{metric}_vs_{comparator}"] = paired_proportion_test(
                v.candidate.y_true,
                v.candidate.y_score,
                comparators[comparator].y_score,
                metric=metric,
                threshold=threshold,
                margin=criterion.margin,
                alpha=ctx.require_alpha(),
                seed=ctx.seed,
                n_replicates=ctx.n_replicates,
            )
    failed = [k for k, r in results.items() if not r.non_inferior]
    details = {"threshold": threshold, "tests": {k: _as_dict(r) for k, r in results.items()}}
    summary = "; ".join(
        f"{k.replace('_vs_', ' vs ')}: {r.delta:+.4f} (lower {r.ci_lower:+.4f}, margin -{r.margin})"
        for k, r in results.items()
    )
    if failed:
        return Finding(
            "PERF-002", Status.FAIL, f"Inferior at threshold {threshold}: {summary}", details
        )
    return Finding(
        "PERF-002", Status.PASS, f"Non-inferior at threshold {threshold}: {summary}", details
    )


@check(
    "PERF-003",
    Family.PERF,
    "Calibration slope and intercept are within bounds",
    Breaks.FAILED,
    "AI Act Art. 15 accuracy",
)
def calibration_bounds(ctx: Context) -> Finding:
    """Point estimates of slope and intercept must lie inside the plan's bounds."""
    if (skip := skipped("PERF-003", ctx)) is not None:
        return skip
    criteria = [c for c in ctx.plan.performance.criteria if isinstance(c, WithinCriterion)]
    if not criteria:
        return Finding("PERF-003", Status.NOT_APPLICABLE, "No calibration criterion in the plan")
    v = ctx.require_versions()
    try:
        candidate = calibration(v.candidate.y_true, v.candidate.y_score)
    except StatsError as exc:
        return Finding("PERF-003", Status.FAIL, f"Calibration cannot be estimated: {exc.summary}")
    try:
        previous: dict[str, Any] | None = _as_dict(
            calibration(v.previous.y_true, v.previous.y_score)
        )
    except StatsError:
        previous = None
    values = {"calibration_slope": candidate.slope, "calibration_intercept": candidate.intercept}
    outside = []
    for criterion in criteria:
        value = values[criterion.metric]
        low, high = criterion.bounds
        if not low <= value <= high:
            name = criterion.metric.removeprefix("calibration_")
            outside.append(f"{name} {value:.3f} not in [{low}, {high}]")
    details = {
        "candidate": _as_dict(candidate),
        "previous": previous,
        "bounds": {c.metric: list(c.bounds) for c in criteria},
        "curve": {
            name: _curve(binned_curve(v.candidate.y_true, preds.y_score))
            for name, preds in (("candidate", v.candidate), ("previous", v.previous))
        },
    }
    if outside:
        return Finding("PERF-003", Status.FAIL, "Miscalibrated: " + "; ".join(outside), details)
    return Finding(
        "PERF-003",
        Status.PASS,
        f"Calibration within bounds (slope {candidate.slope:.3f}, "
        f"intercept {round(candidate.intercept, 3) + 0.0:+.3f})",
        details,
    )


@check(
    "PERF-004",
    Family.PERF,
    "Net benefit at clinical thresholds is non-inferior (paired bootstrap)",
    Breaks.FAILED,
    "Evidence-based principle; clinical utility",
)
def net_benefit_non_inferior(ctx: Context) -> Finding:
    """Paired bootstrap percentile interval of the net benefit difference at each threshold."""
    if (skip := skipped("PERF-004", ctx)) is not None:
        return skip
    criteria = _criteria(ctx, ("net_benefit",))
    if not criteria:
        return Finding("PERF-004", Status.NOT_APPLICABLE, "No net benefit criterion in the plan")
    v = ctx.require_versions()
    comparators = {"previous": v.previous, "anchor": v.anchor}
    level = 1.0 - 2.0 * ctx.require_alpha()
    results: dict[str, dict[str, Any]] = {}
    failed = []
    for criterion in criteria:
        for comparator in criterion.vs:
            for t in criterion.at_thresholds or []:
                boot = net_benefit_difference(
                    v.candidate.y_true,
                    v.candidate.y_score,
                    comparators[comparator].y_score,
                    t,
                    n_replicates=ctx.n_replicates,
                    level=level,
                    seed=ctx.seed,
                )
                key = f"t{t:g}_vs_{comparator}"
                lower = boot.percentile[0]
                ok = lower > -criterion.margin
                results[key] = {
                    "threshold": t,
                    "comparator": comparator,
                    "delta": boot.estimate,
                    "ci_lower": lower,
                    "ci_upper": boot.percentile[1],
                    "bca": list(boot.bca),
                    "margin": criterion.margin,
                    "non_inferior": ok,
                }
                if not ok:
                    failed.append(f"t={t:g} vs {comparator} (lower {lower:+.4f})")
    grid = [round(0.01 * i, 2) for i in range(1, 51)]
    curve = {
        "thresholds": grid,
        "candidate": decision_curve(v.candidate.y_true, v.candidate.y_score, grid).model.tolist(),
        "previous": decision_curve(v.candidate.y_true, v.previous.y_score, grid).model.tolist(),
        "treat_all": decision_curve(
            v.candidate.y_true, v.candidate.y_score, grid
        ).treat_all.tolist(),
        "plan_thresholds": sorted({t for c in criteria for t in c.at_thresholds or []}),
    }
    details = {
        "level": level,
        "replicates": ctx.n_replicates,
        "seed": ctx.seed,
        "tests": results,
        "curve": curve,
    }
    if failed:
        return Finding(
            "PERF-004", Status.FAIL, "Net benefit inferior at " + ", ".join(failed), details
        )
    return Finding(
        "PERF-004",
        Status.PASS,
        f"Net benefit non-inferior at {len(results)} threshold comparison(s)",
        details,
    )


@check(
    "PERF-005",
    Family.PERF,
    "No subgroup loses more than the allowed AUROC",
    Breaks.FAILED,
    "Transparency principle; AI Act Art. 10 bias",
)
def subgroup_drop(ctx: Context) -> Finding:
    """Per-subgroup non-inferiority against the previous version, with Holm or Bonferroni."""
    if (skip := skipped("PERF-005", ctx)) is not None:
        return skip
    rule = ctx.plan.performance.subgroups
    if rule is None:
        return Finding("PERF-005", Status.NOT_APPLICABLE, "No subgroup criterion in the plan")
    v = ctx.require_versions()
    y = v.candidate.y_true
    alpha = ctx.require_alpha()
    groups: list[dict[str, Any]] = []
    tests: list[PairedAucTest] = []
    for column in rule.by:
        labels = v.candidate.subgroups[column]
        for level in sorted(set(labels.tolist())):
            members = labels == level
            n_pos = int(y[members].sum())
            n_neg = int(members.sum()) - n_pos
            entry: dict[str, Any] = {
                "column": column,
                "level": level,
                "n_pos": n_pos,
                "n_neg": n_neg,
            }
            if min(n_pos, n_neg) < max(rule.min_events, 2):
                entry["status"] = "insufficient"
                groups.append(entry)
                continue
            result = delong(y[members], v.candidate.y_score[members], v.previous.y_score[members])
            test = paired_test_from(result, 0, 1, margin=rule.max_drop, alpha=alpha)
            entry.update({"delta": test.delta, "se": test.se, "p_value": test.p_value})
            entry["_test"] = len(tests)
            tests.append(test)
            groups.append(entry)
    correction = holm if rule.multiplicity == "holm" else bonferroni
    adjustment = correction([t.p_value for t in tests], alpha)
    harmed = []
    for entry in groups:
        index = entry.pop("_test", None)
        if index is None:
            continue
        level_used = adjustment.levels[index]
        test = tests[index]
        half_width = norm_ppf(1.0 - level_used) * test.se
        entry.update(
            {
                "alpha_used": level_used,
                "ci_lower": test.delta - half_width,
                "ci_upper": test.delta + half_width,
                "adjusted_p": adjustment.adjusted_p[index],
                "status": "pass" if adjustment.rejected[index] else "fail",
            }
        )
        if not adjustment.rejected[index]:
            harmed.append(f"{entry['column']}={entry['level']} ({test.delta:+.3f})")
    insufficient = [f"{e['column']}={e['level']}" for e in groups if e["status"] == "insufficient"]
    details = {
        "max_drop": rule.max_drop,
        "min_events": rule.min_events,
        "multiplicity": rule.multiplicity,
        "alpha": alpha,
        "subgroups": groups,
    }
    if harmed:
        return Finding(
            "PERF-005",
            Status.FAIL,
            "Subgroup AUROC drop beyond the limit: " + ", ".join(harmed),
            details,
        )
    if insufficient:
        text = "Insufficient evidence in " + ", ".join(insufficient)
        status = Status.FAIL if rule.on_insufficient == "fail" else Status.WARN
        return Finding("PERF-005", status, text, details)
    return Finding(
        "PERF-005", Status.PASS, f"All {len(tests)} subgroups within the allowed drop", details
    )


@check(
    "PERF-006",
    Family.PERF,
    "Test set has power to detect the margin",
    Breaks.WARNING,
    "Evidence-based principle",
)
def power_check(ctx: Context) -> Finding:
    """Analytic power of the AUROC test against the previous version."""
    if (skip := skipped("PERF-006", ctx)) is not None:
        return skip
    requirement = ctx.plan.performance.power
    criteria = _criteria(ctx, ("auroc",))
    if requirement is None or not criteria:
        return Finding("PERF-006", Status.NOT_APPLICABLE, "No power requirement or AUROC criterion")
    aucs = ctx.aucs
    auc_prev = min(max(float(aucs.auc[1]), 0.5), 0.999)
    var0, var1 = float(aucs.cov[0, 0]), float(aucs.cov[1, 1])
    correlation = float(aucs.cov[0, 1]) / math.sqrt(var0 * var1) if var0 > 0 and var1 > 0 else 0.0
    correlation = min(max(correlation, -0.99), 0.99)
    margin = criteria[0].margin
    power = analytic_power(
        auc=auc_prev,
        n_pos=aucs.n_pos,
        n_neg=aucs.n_neg,
        margin=margin,
        alpha=ctx.require_alpha(),
        correlation=correlation,
    )
    details = {
        "power": power,
        "min_power": requirement.min_power,
        "auc": auc_prev,
        "n_pos": aucs.n_pos,
        "n_neg": aucs.n_neg,
        "margin": margin,
        "alpha": ctx.require_alpha(),
        "correlation": correlation,
    }
    if power < requirement.min_power:
        return Finding(
            "PERF-006",
            Status.WARN,
            f"Power {power:.2f} to detect the AUROC margin {margin} "
            f"is below {requirement.min_power}",
            details,
        )
    return Finding(
        "PERF-006", Status.PASS, f"Power {power:.2f} to detect the AUROC margin {margin}", details
    )

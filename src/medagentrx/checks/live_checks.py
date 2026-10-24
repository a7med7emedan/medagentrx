# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""LIVE checks: is the deployed system still the one that was released?

A deployment QC run scores a locked set of raw control records with the live
stack. A change in libraries, runtime, hardware or preprocessing can move the
scores without any change to the model weights. Every LIVE failure is an
undeclared update, so it breaks the plan.
"""

from __future__ import annotations

import math

import numpy as np

from medagentrx.checks.qc_context import QcContext
from medagentrx.checks.registry import Breaks, Family, Finding, Status, check
from medagentrx.io.fingerprint import id_fingerprint
from medagentrx.stats.multirule import (
    RULE_TEXT,
    Baseline,
    estimate_baseline,
    evaluate_rules,
    given_baseline,
    standardise,
)

WORST_SHOWN = 5
HISTORY_SHOWN = 60
SD_FLOOR_SHARE = 3.0
"""Records are allowed to vary with an SD of up to the tolerance divided by this."""


def sd_floor(tolerance: float, records: int) -> float:
    """Smallest SD of the run bias used by the multirule check.

    It is the SD the bias would have if every one of ``records`` control
    records varied independently with an SD of a third of the tolerance, the
    most noise the plan accepts. A deterministic stack has a zero SD, and the
    floor keeps rounding from counting as a shift without blunting the rules.
    """
    return tolerance / (SD_FLOOR_SHARE * math.sqrt(records))


def _deviations(ctx: QcContext) -> tuple[list[str], np.ndarray]:
    expected = ctx.expected.by_id()
    ids = ctx.live.row_id.tolist()
    values = np.array([expected[i] for i in ids], dtype=np.float64)
    return ids, ctx.live.y_score - values


def run_bias(ctx: QcContext) -> float:
    """Mean of live minus expected score over the control records."""
    return float(np.mean(_deviations(ctx)[1]))


def _skipped(check_id: str, ctx: QcContext) -> Finding | None:
    blocker = ctx.measurement_blocker
    if blocker is None:
        return None
    return Finding(check_id, Status.SKIPPED, f"Not assessed: {blocker}")


@check(
    "LIVE-001",
    Family.LIVE,
    "Live version is the released one",
    Breaks.OUTSIDE_PLAN,
    "Update procedures; post-market monitoring",
)
def live_version(ctx: QcContext) -> Finding:
    """The version running live must be the latest released version.

    The released version is the latest ``release`` record in the ledger, or the
    plan's anchor version when no release has been recorded. Any other version
    running in production is itself an undeclared update.
    """
    details = {"model_version": ctx.model_version, "released_version": ctx.released_version}
    if ctx.model_version != ctx.released_version:
        return Finding(
            "LIVE-001",
            Status.FAIL,
            f"Version {ctx.model_version} is running live, but the released version is "
            f"{ctx.released_version}",
            details,
        )
    return Finding(
        "LIVE-001", Status.PASS, f"Version {ctx.model_version} is the released version", details
    )


@check(
    "LIVE-002",
    Family.LIVE,
    "Score file is bound to the control set",
    Breaks.OUTSIDE_PLAN,
    "Traceability; post-market monitoring",
)
def score_binding(ctx: QcContext) -> Finding:
    """Live and expected scores must cover exactly the locked control ids.

    The ids are compared by fingerprint, the expected score file by its SHA-256
    in the plan, and the raw control inputs, when supplied, by theirs.
    """
    qc = ctx.qc
    problems: list[str] = []
    live_ids = id_fingerprint(ctx.live.row_id.tolist())
    expected_ids = id_fingerprint(ctx.expected.row_id.tolist())
    if live_ids != qc.control_ids_fingerprint:
        problems.append("the live score file does not cover exactly the control ids")
    if expected_ids != qc.control_ids_fingerprint:
        problems.append("the expected score file does not cover exactly the control ids")
    planned = qc.expected_scores.get(ctx.model_version)
    if planned is None:
        problems.append(
            f"the plan records no expected scores for version {ctx.model_version}; "
            "add them with medagentrx qc init --version"
        )
    elif planned != ctx.expected_sha256:
        problems.append(
            f"the expected score file is not the one the plan records for {ctx.model_version}"
        )
    if ctx.control_inputs_sha256 is not None and (
        ctx.control_inputs_sha256 != qc.control_inputs_sha256
    ):
        problems.append("the raw control inputs differ from the locked control file")
    details = {
        "live_ids_fingerprint": live_ids,
        "expected_ids_fingerprint": expected_ids,
        "control_ids_fingerprint": qc.control_ids_fingerprint,
        "records": ctx.live.n,
        "control_inputs_checked": ctx.control_inputs_sha256 is not None,
        "problems": problems,
    }
    if problems:
        return Finding("LIVE-002", Status.FAIL, "; ".join(problems).capitalize(), details)
    checked = " and the raw control inputs" if ctx.control_inputs_sha256 is not None else ""
    return Finding(
        "LIVE-002",
        Status.PASS,
        f"Scores cover the {ctx.live.n} locked control records{checked}",
        details,
    )


@check(
    "LIVE-003",
    Family.LIVE,
    "Every control record is within tolerance",
    Breaks.OUTSIDE_PLAN,
    "Post-market monitoring; AI Act Art. 15 accuracy",
)
def record_tolerance(ctx: QcContext) -> Finding:
    """No control record may move further from its expected score than the tolerance."""
    if (skip := _skipped("LIVE-003", ctx)) is not None:
        return skip
    tolerance = ctx.qc.tolerance.absolute
    ids, deviation = _deviations(ctx)
    absolute = np.abs(deviation)
    order = np.argsort(-absolute, kind="stable")[:WORST_SHOWN]
    expected = ctx.expected.by_id()
    worst = [
        {
            "row_id": ids[i],
            "live": float(ctx.live.y_score[i]),
            "expected": expected[ids[i]],
            "deviation": float(deviation[i]),
        }
        for i in order
    ]
    largest = float(absolute.max())
    over = int(np.count_nonzero(absolute > tolerance))
    details = {
        "tolerance": tolerance,
        "max_abs_deviation": largest,
        "bias": float(np.mean(deviation)),
        "records_over_tolerance": over,
        "records": len(ids),
        "worst": worst,
    }
    if largest > tolerance:
        return Finding(
            "LIVE-003",
            Status.FAIL,
            f"{over} of {len(ids)} control records moved more than {tolerance:g} "
            f"(largest {largest:.3g})",
            details,
        )
    return Finding(
        "LIVE-003",
        Status.PASS,
        f"All {len(ids)} control records within {tolerance:g} (largest {largest:.3g})",
        details,
    )


def qc_baseline(ctx: QcContext) -> tuple[Baseline | None, int]:
    """The baseline for this run, or None while it is still being collected.

    Returns the baseline and the number of in-control runs recorded before
    this one. Rejected runs never join the baseline.
    """
    qc = ctx.qc
    accepted = [run.bias for run in ctx.history if run.in_control]
    if qc.sd is not None:
        return given_baseline(qc.sd), len(accepted)
    if len(accepted) < qc.baseline_runs:
        return None, len(accepted)
    floor = sd_floor(qc.tolerance.absolute, ctx.live.n)
    return estimate_baseline(accepted[: qc.baseline_runs], floor=floor), len(accepted)


@check(
    "LIVE-004",
    Family.LIVE,
    "Run bias passes the multirule QC rules",
    Breaks.OUTSIDE_PLAN,
    "Westgard et al. 1981; post-market monitoring",
)
def multirule(ctx: QcContext) -> Finding:
    """Westgard multirule on the run bias over this version's run history.

    1_2s gives a warning. 1_3s, 2_2s, R_4s and 10_x reject the run. Until the
    baseline is complete, only LIVE-001 to LIVE-003 apply.
    """
    if (skip := _skipped("LIVE-004", ctx)) is not None:
        return skip
    qc = ctx.qc
    bias = run_bias(ctx)
    baseline, prior = qc_baseline(ctx)
    if baseline is None:
        return Finding(
            "LIVE-004",
            Status.NOT_APPLICABLE,
            f"Baseline run {prior + 1} of {qc.baseline_runs}: multirule QC starts once the "
            "baseline is complete; LIVE-001 to LIVE-003 apply meanwhile",
            {"bias": bias, "baseline_runs_done": prior + 1, "baseline_runs": qc.baseline_runs},
        )
    window = [run.bias for run in ctx.history if run.in_control] + [bias]
    z = standardise(window, baseline)
    outcome = evaluate_rules(z, qc.rules)
    details = {
        "bias": bias,
        "z": z[-1],
        "mean": baseline.mean,
        "sd": baseline.sd,
        "estimated_sd": baseline.estimated_sd,
        "sd_floored": baseline.floored,
        "baseline_runs": baseline.runs,
        "rules": list(qc.rules),
        "rejections": list(outcome.rejections),
        "warnings": list(outcome.warnings),
        "z_history": list(z[-HISTORY_SHOWN:]),
    }
    position = f"bias {bias:.3g}, {z[-1]:+.2f} SD"
    if outcome.rejections:
        fired = "; ".join(f"{r}: {RULE_TEXT[r]}" for r in outcome.rejections)
        return Finding("LIVE-004", Status.FAIL, f"Rejected ({position}). {fired}", details)
    if outcome.warnings:
        return Finding(
            "LIVE-004",
            Status.WARN,
            f"Warning ({position}). 1_2s: {RULE_TEXT['1_2s']}",
            details,
        )
    return Finding("LIVE-004", Status.PASS, f"In control ({position})", details)

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""DATA checks: was the update trained and tested on the data the plan allows?"""

from __future__ import annotations

import math
from collections.abc import Sequence

from medagentrx.checks.context import Context
from medagentrx.checks.registry import Breaks, Family, Finding, Status, check
from medagentrx.io.predictions import ROW_ID
from medagentrx.plan.conditions import evaluate
from medagentrx.stats.smd import SMD_WARNING, categorical_smd, numeric_smd

EXAMPLES = 5
MAX_LEVELS = 50
"""Categorical columns with more levels are identifiers, not features, and are skipped."""


@check(
    "DATA-001",
    Family.DATA,
    "Locked test set is unchanged",
    Breaks.OUTSIDE_PLAN,
    "Modification Protocol, data management",
)
def locked_test_set(ctx: Context) -> Finding:
    """Fingerprint must match the plan, and all versions must share rows and labels."""
    planned = ctx.plan.data_management.locked_test_set.sha256
    details: dict[str, object] = {
        "plan_fingerprint": planned,
        "candidate_fingerprint": ctx.test_fingerprint,
        "rows": ctx.candidate.n,
        "mismatches": {name: m.describe() for name, m in ctx.mismatches.items()},
    }
    if not ctx.test_set_is_locked:
        return Finding(
            "DATA-001",
            Status.FAIL,
            "Test set fingerprint does not match the plan; rows or labels have changed",
            details,
        )
    if ctx.mismatches:
        names = ", ".join(sorted(ctx.mismatches))
        return Finding(
            "DATA-001",
            Status.FAIL,
            f"Prediction files for {names} do not have the same rows and labels as the candidate",
            details,
        )
    return Finding(
        "DATA-001", Status.PASS, f"Locked test set matches ({ctx.candidate.n} rows)", details
    )


def _test_keys(ctx: Context, key: str) -> set[str]:
    if key == ROW_ID:
        return set(ctx.candidate.row_id.tolist())
    return set(ctx.candidate.subgroups[key].tolist())


def _train_keys(ctx: Context, key: str) -> set[str]:
    manifest = ctx.manifest
    if key == ROW_ID:
        return set(manifest.row_id)
    if key == "patient_id":
        return set(manifest.patient_id)
    return {str(v) for v in manifest.columns[key] if v is not None}


@check(
    "DATA-002",
    Family.DATA,
    "No overlap between training and test data",
    Breaks.FAILED,
    "Data management; test data sequestration",
)
def no_overlap(ctx: Context) -> Finding:
    """No value of a ``forbid_overlap_on`` key may occur in both training and test data."""
    overlaps: dict[str, dict[str, object]] = {}
    for key in ctx.plan.data_management.forbid_overlap_on:
        shared = sorted(_test_keys(ctx, key) & _train_keys(ctx, key))
        if shared:
            overlaps[key] = {"count": len(shared), "examples": shared[:EXAMPLES]}
    details = {"keys": list(ctx.plan.data_management.forbid_overlap_on), "overlaps": overlaps}
    if overlaps:
        summary = "; ".join(f"{k}: {v['count']}" for k, v in overlaps.items())
        return Finding(
            "DATA-002", Status.FAIL, f"Training data overlaps the test set ({summary})", details
        )
    return Finding(
        "DATA-002", Status.PASS, "No training row shares a key with the test set", details
    )


@check(
    "DATA-003",
    Family.DATA,
    "Every training row meets the inclusion criteria",
    Breaks.OUTSIDE_PLAN,
    "Data management; AI Act Art. 10",
)
def training_inclusion(ctx: Context) -> Finding:
    """Every manifest row must satisfy ``training_inclusion``.

    The manifest must also be the one named in the model metadata, or the
    training data cannot be verified.
    """
    manifest = ctx.manifest
    if ctx.manifest_sha256 != ctx.meta.training_manifest_sha256:
        return Finding(
            "DATA-003",
            Status.FAIL,
            "Training manifest does not match training_manifest_sha256 in the model metadata",
            {"manifest_sha256": ctx.manifest_sha256, "metadata": ctx.meta.training_manifest_sha256},
        )
    condition = ctx.plan.data_management.training_inclusion
    names = list(manifest.columns)
    failing: list[str] = []
    for i, row_id in enumerate(manifest.row_id):
        row = {name: manifest.columns[name][i] for name in names}
        if not evaluate(condition, row):
            failing.append(row_id)
    details = {"rows": manifest.n, "failing": len(failing), "examples": failing[:EXAMPLES]}
    if failing:
        return Finding(
            "DATA-003",
            Status.FAIL,
            f"{len(failing)} of {manifest.n} training rows do not meet the inclusion criteria",
            details,
        )
    return Finding(
        "DATA-003",
        Status.PASS,
        f"All {manifest.n} training rows meet the inclusion criteria",
        details,
    )


@check(
    "DATA-004",
    Family.DATA,
    "Test-set evaluation budget is not exceeded",
    Breaks.OUTSIDE_PLAN,
    "Test data sequestration; adaptive overfitting (Dwork et al. 2015)",
)
def evaluation_budget(ctx: Context) -> Finding:
    """This look must fit inside ``max_evaluations``."""
    limit = ctx.plan.data_management.locked_test_set.max_evaluations
    used = ctx.history.looks_used
    details = {"looks_used_before": used, "max_evaluations": limit, "this_look": used + 1}
    if used >= limit:
        return Finding(
            "DATA-004",
            Status.FAIL,
            f"All {limit} looks at the locked test set have been used",
            details,
        )
    return Finding(
        "DATA-004", Status.PASS, f"Look {used + 1} of {limit} at the locked test set", details
    )


def _numeric(values: Sequence[object]) -> list[float] | None:
    out: list[float] = []
    for value in values:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            out.append(float(value))
            continue
        try:
            number = float(str(value))
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        out.append(number)
    return out


@check(
    "DATA-005",
    Family.DATA,
    "Population shift between training and test data",
    Breaks.WARNING,
    "Evidence-based principle",
)
def population_shift(ctx: Context) -> Finding:
    """Warn when a shared feature has |SMD| above 0.1 between training and test data."""
    if not ctx.test_features:
        return Finding(
            "DATA-005",
            Status.NOT_APPLICABLE,
            "No feature columns shared by training and test files",
        )
    smds: dict[str, float] = {}
    too_many_levels: list[str] = []
    for name, test_values in ctx.test_features.items():
        train = [v for v in ctx.manifest.columns[name] if v is not None and v != ""]
        test = [v for v in test_values if v != ""]
        if len(train) < 2 or len(test) < 2:
            continue
        train_num, test_num = _numeric(train), _numeric(test)
        if train_num is not None and test_num is not None:
            smds[name] = numeric_smd(train_num, test_num)
        else:
            train_text, test_text = [str(v) for v in train], [str(v) for v in test]
            if len(set(train_text) | set(test_text)) > MAX_LEVELS:
                too_many_levels.append(name)
                continue
            smds[name] = categorical_smd(train_text, test_text)
    shifted = {k: v for k, v in smds.items() if abs(v) > SMD_WARNING}
    details = {
        "smd": smds,
        "threshold": SMD_WARNING,
        "shifted": sorted(shifted),
        "skipped_high_cardinality": too_many_levels,
    }
    if shifted:
        listed = ", ".join(f"{k} ({v:+.2f})" for k, v in sorted(shifted.items()))
        return Finding(
            "DATA-005", Status.WARN, f"Population shift above {SMD_WARNING}: {listed}", details
        )
    return Finding(
        "DATA-005", Status.PASS, f"No feature shifts by more than {SMD_WARNING} SMD", details
    )


@check(
    "DATA-006",
    Family.DATA,
    "Prediction files are the ones the models produced",
    Breaks.OUTSIDE_PLAN,
    "Traceability; Modification Protocol, update procedures",
)
def prediction_provenance(ctx: Context) -> Finding:
    """Bind each prediction file to its model.

    The candidate file must match ``predictions_sha256`` in its metadata. The
    previous file must match the predictions recorded when that version was
    released, if the ledger holds them. The anchor file must match
    ``anchor_predictions_sha256`` in the plan, if the plan records it.
    """
    actual = ctx.prediction_sha256
    expected: dict[str, str | None] = {
        "candidate": ctx.meta.predictions_sha256,
        "previous": ctx.history.released_predictions.get(ctx.meta.previous_version),
        "anchor": ctx.plan.anchor_predictions_sha256,
    }
    mismatched = [
        role for role, want in expected.items() if want is not None and actual[role] != want
    ]
    unchecked = [role for role, want in expected.items() if want is None]
    details = {"expected": expected, "actual": actual, "not_bound": unchecked}
    if mismatched:
        return Finding(
            "DATA-006",
            Status.FAIL,
            "Prediction file(s) differ from the recorded model output: " + ", ".join(mismatched),
            details,
        )
    text = "Prediction files match the recorded model outputs"
    if unchecked:
        text += f" ({', '.join(unchecked)} not yet bound)"
    return Finding("DATA-006", Status.PASS, text, details)

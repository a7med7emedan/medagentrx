# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Run every check on one candidate update and decide the verdict.

Verdict rule: any failed check that breaks the plan gives OUTSIDE_PLAN.
Otherwise any failed check gives FAILED. Otherwise ACCEPTED. Warnings never
change the verdict.

An invalid plan gives OUTSIDE_PLAN through PLAN-001 with every other check
skipped. Unreadable or invalid input files raise ``InputError`` instead,
which the command line reports with exit code 3.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from medagentrx import __version__
from medagentrx.checks import REGISTRY, Breaks, Finding, Status, catalogue
from medagentrx.checks.context import Context, Versions
from medagentrx.errors import PlanError
from medagentrx.exit_codes import ExitCode
from medagentrx.history import History
from medagentrx.io.fingerprint import test_set_fingerprint
from medagentrx.io.hashing import sha256_file
from medagentrx.io.limits import Limits
from medagentrx.io.manifest import PATIENT_ID, load_manifest
from medagentrx.io.metadata import load_model_meta
from medagentrx.io.paths import resolve_input
from medagentrx.io.predictions import (
    ROW_ID,
    Y_SCORE,
    Y_TRUE,
    RowMismatch,
    RowMismatchError,
    align,
    load_predictions,
)
from medagentrx.io.tables import peek_columns, read_table
from medagentrx.plan import load_plan, plan_fingerprint
from medagentrx.plan.conditions import condition_fields
from medagentrx.stats.alpha import AlphaState, initial_state, next_alpha, record
from medagentrx.stats.bootstrap import DEFAULT_REPLICATES


class Verdict(StrEnum):
    """The single outcome of an evaluation."""

    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"
    OUTSIDE_PLAN = "OUTSIDE_PLAN"

    @property
    def exit_code(self) -> ExitCode:
        """Process exit code for this verdict."""
        return ExitCode[self.name]


def decide(findings: list[Finding]) -> Verdict:
    """Apply the verdict rule to a list of findings."""
    failed = [f for f in findings if f.status is Status.FAIL]
    if any(f.spec.breaks is Breaks.OUTSIDE_PLAN for f in failed):
        return Verdict.OUTSIDE_PLAN
    if failed:
        return Verdict.FAILED
    if any(f.status is Status.SKIPPED for f in findings):  # pragma: no cover  # invariant
        raise RuntimeError("a check was skipped without an OUTSIDE_PLAN finding")
    return Verdict.ACCEPTED


@dataclass(frozen=True)
class Evaluation:
    """Everything decided about one candidate update.

    Attributes:
        verdict: ACCEPTED, FAILED or OUTSIDE_PLAN.
        findings: One finding per check, in catalogue order.
        plan_id: Plan identifier, or None if the plan was invalid.
        plan_revision: Plan revision, or None if the plan was invalid.
        plan_fingerprint: Plan fingerprint, or None if the plan was invalid.
        candidate_version: Version of the candidate model.
        previous_version: Version it replaces.
        modification_id: Plan modification claimed.
        test_fingerprint: Fingerprint of the candidate's test rows.
        alpha_method: Alpha spending rule of the plan.
        alpha_used: Level used for this evaluation, or None if no test ran.
        touched_test_set: Whether the locked test set was evaluated.
        inputs: SHA-256 of every input file by role.
        seed: Seed used for resampling.
        n_replicates: Bootstrap replicates.
        evaluated_at: Time of the evaluation.
        tool_version: Version of this package.
    """

    verdict: Verdict
    findings: tuple[Finding, ...]
    plan_id: str | None
    plan_revision: int | None
    plan_fingerprint: str | None
    candidate_version: str | None
    previous_version: str | None
    modification_id: str | None
    test_fingerprint: str | None
    alpha_method: str | None
    alpha_used: float | None
    touched_test_set: bool
    inputs: dict[str, str]
    seed: int
    n_replicates: int
    evaluated_at: dt.datetime
    tool_version: str = __version__
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def exit_code(self) -> ExitCode:
        """Process exit code for the verdict."""
        return self.verdict.exit_code

    def finding(self, check_id: str) -> Finding:
        """The finding of one check."""
        for item in self.findings:
            if item.check_id == check_id:
                return item
        raise KeyError(check_id)

    @property
    def failed_checks(self) -> list[str]:
        """Identifiers of failed checks."""
        return [f.check_id for f in self.findings if f.status is Status.FAIL]

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible form, used by the reports and the ledger."""
        return {
            "verdict": self.verdict.value,
            "exit_code": int(self.exit_code),
            "plan": {
                "id": self.plan_id,
                "revision": self.plan_revision,
                "fingerprint": self.plan_fingerprint,
            },
            "candidate_version": self.candidate_version,
            "previous_version": self.previous_version,
            "modification_id": self.modification_id,
            "test_fingerprint": self.test_fingerprint,
            "alpha": {"method": self.alpha_method, "used": self.alpha_used},
            "touched_test_set": self.touched_test_set,
            "inputs": dict(self.inputs),
            "seed": self.seed,
            "n_replicates": self.n_replicates,
            "evaluated_at": self.evaluated_at.isoformat(),
            "tool_version": self.tool_version,
            "notes": list(self.notes),
            "checks": [
                {
                    "id": f.check_id,
                    "title": f.spec.title,
                    "family": f.spec.family.value,
                    "breaks": f.spec.breaks.value,
                    "cross_reference": f.spec.cross_reference,
                    "status": f.status.value,
                    "message": f.message,
                    "details": json_safe(f.details),
                }
                for f in self.findings
            ],
        }


def json_safe(value: Any) -> Any:  # noqa: ANN401
    """Return ``value`` with non-finite floats written as strings, so JSON stays strict.

    Infinity arises legitimately, for example a z statistic when two models
    give identical scores.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    return value


def _invalid_plan(error: PlanError, now: dt.datetime, seed: int, n_replicates: int) -> Evaluation:
    findings = [Finding("PLAN-001", Status.FAIL, str(error), {"errors": list(error.details)})]
    findings += [
        Finding(spec.check_id, Status.SKIPPED, "Not assessed: the plan is not valid (PLAN-001)")
        for spec in catalogue()
        if spec.check_id != "PLAN-001"
    ]
    return Evaluation(
        verdict=decide(findings),
        findings=tuple(findings),
        plan_id=None,
        plan_revision=None,
        plan_fingerprint=None,
        candidate_version=None,
        previous_version=None,
        modification_id=None,
        test_fingerprint=None,
        alpha_method=None,
        alpha_used=None,
        touched_test_set=False,
        inputs={},
        seed=seed,
        n_replicates=n_replicates,
        evaluated_at=now,
    )


def evaluate(
    *,
    plan: str | Path,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    manifest: str | Path,
    model_meta: str | Path,
    history: History | None = None,
    seed: int = 0,
    n_replicates: int = DEFAULT_REPLICATES,
    limits: Limits | None = None,
    now: dt.datetime | None = None,
    base: Path | None = None,
) -> Evaluation:
    """Evaluate one candidate update against its change plan.

    Args:
        plan: ``change-plan.yaml``.
        candidate: Candidate predictions on the locked test set.
        previous: Predictions of the version being replaced.
        anchor: Predictions of the originally authorised version.
        manifest: Training data manifest of the candidate.
        model_meta: ``model.yaml`` of the candidate.
        history: Budgets used so far, from the ledger. Empty if None.
        seed: Seed for every resampling step.
        n_replicates: Bootstrap replicates.
        limits: Input size limits.
        now: Evaluation time. Defaults to the current UTC time.
        base: Directory input symlinks may point into.

    Raises:
        InputError: If an input file other than the plan is missing or invalid.
    """
    history = history or History()
    now = now or dt.datetime.now(dt.UTC)
    try:
        change_plan = load_plan(plan)
    except PlanError as error:
        return _invalid_plan(error, now, seed, n_replicates)
    fingerprint = plan_fingerprint(change_plan)
    meta = load_model_meta(model_meta, base=base)

    subgroup_columns = (
        list(change_plan.performance.subgroups.by) if change_plan.performance.subgroups else []
    )
    key_columns = [k for k in change_plan.data_management.forbid_overlap_on if k != ROW_ID]
    extra = list(dict.fromkeys([*subgroup_columns, *key_columns]))
    cand = load_predictions(candidate, subgroup_columns=extra, limits=limits, base=base)
    prev = load_predictions(previous, limits=limits, base=base)
    anch = load_predictions(anchor, limits=limits, base=base)

    mismatches: dict[str, RowMismatch] = {}
    aligned: dict[str, Any] = {}
    for name, other in (("previous", prev), ("anchor", anch)):
        try:
            aligned[name] = align(cand, other)
        except RowMismatchError as exc:
            mismatches[name] = exc.mismatch
    versions = None if mismatches else Versions(cand, aligned["previous"], aligned["anchor"])

    train = load_manifest(
        manifest,
        required_fields=condition_fields(change_plan.data_management.training_inclusion),
        limits=limits,
        base=base,
    )
    reserved = {ROW_ID, PATIENT_ID, Y_TRUE, Y_SCORE, *key_columns}
    header = peek_columns(candidate, limits=limits, base=base)
    shared = [c for c in header if c in train.columns and c not in reserved]
    test_features: dict[str, tuple[str, ...]] = {}
    if shared:
        raw = read_table(candidate, required=shared, limits=limits, base=base)
        test_features = {
            name: tuple("" if v is None else str(v) for v in raw.columns[name]) for name in shared
        }

    state = history.alpha or initial_state(
        change_plan.performance.alpha_spending,
        change_plan.performance.alpha_total,
        change_plan.max_updates,
    )
    alpha = None if state.exhausted else next_alpha(state)
    ctx = Context(
        plan=change_plan,
        plan_fingerprint=fingerprint,
        meta=meta,
        candidate=cand,
        test_fingerprint=test_set_fingerprint(cand),
        versions=versions,
        mismatches=mismatches,
        manifest=train,
        manifest_sha256=sha256_file(resolve_input(manifest, base=base)),
        test_features=test_features,
        history=history,
        alpha_state=state,
        alpha=alpha,
        seed=seed,
        n_replicates=n_replicates,
        now=now,
    )
    findings = [spec.run(ctx) for spec in catalogue()]
    touched = ctx.performance_blocker is None
    inputs = {
        role: sha256_file(resolve_input(path, base=base))
        for role, path in (
            ("plan", plan),
            ("candidate", candidate),
            ("previous", previous),
            ("anchor", anchor),
            ("manifest", manifest),
            ("model_meta", model_meta),
        )
    }
    return Evaluation(
        verdict=decide(findings),
        findings=tuple(findings),
        plan_id=change_plan.plan.id,
        plan_revision=change_plan.plan.revision,
        plan_fingerprint=fingerprint,
        candidate_version=meta.version,
        previous_version=meta.previous_version,
        modification_id=meta.modification_id,
        test_fingerprint=ctx.test_fingerprint,
        alpha_method=state.method,
        alpha_used=alpha if touched else None,
        touched_test_set=touched,
        inputs=inputs,
        seed=seed,
        n_replicates=n_replicates,
        evaluated_at=now,
        notes=tuple(ctx.notes),
    )


def alpha_after(state: AlphaState, evaluation: Evaluation) -> AlphaState:
    """Alpha state after recording ``evaluation``. Used by the ledger."""
    if evaluation.alpha_used is None:
        return state
    return record(state, evaluation.alpha_used, rejected=evaluation.verdict is Verdict.ACCEPTED)


__all__ = ["REGISTRY", "Evaluation", "Verdict", "alpha_after", "decide", "evaluate"]

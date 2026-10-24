# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Deployment QC: control samples for the live system, as in a clinical lab.

A clinical laboratory does not trust an analyser because its serial number is
unchanged. It runs a control sample with a known answer on a schedule and
stops when the result drifts. ``run_qc`` does the same for a deployed model:
the live system scores a locked set of raw control records, and the scores
are compared with the expected scores of the released version.

A QC run gives IN_CONTROL (exit 0, warnings allowed) or OUTSIDE_PLAN (exit 2).
Every run is written to the ledger, and the run history for the multirule
check is read back from it. QC runs never touch the locked test set.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from medagentrx import __version__
from medagentrx.checks import Breaks, Finding, Status, catalogue
from medagentrx.checks.live_checks import run_bias
from medagentrx.checks.qc_context import QcContext, QcHistoryRun
from medagentrx.checks.registry import QC_FAMILIES
from medagentrx.engine import json_safe
from medagentrx.errors import InputError
from medagentrx.exit_codes import ExitCode
from medagentrx.io.fingerprint import id_fingerprint
from medagentrx.io.hashing import sha256_file
from medagentrx.io.limits import Limits
from medagentrx.io.paths import resolve_input
from medagentrx.io.predictions import load_predictions, load_row_ids, load_scores
from medagentrx.plan import load_plan, plan_fingerprint
from medagentrx.plan.models import ChangePlan, DeploymentQC

QC_KIND = "qc"


class QcVerdict(StrEnum):
    """The outcome of a QC run."""

    IN_CONTROL = "IN_CONTROL"
    OUTSIDE_PLAN = "OUTSIDE_PLAN"

    @property
    def exit_code(self) -> ExitCode:
        """0 for IN_CONTROL, 2 for OUTSIDE_PLAN."""
        return ExitCode.ACCEPTED if self is QcVerdict.IN_CONTROL else ExitCode.OUTSIDE_PLAN


def decide_qc(findings: Sequence[Finding]) -> QcVerdict:
    """Any failed LIVE check gives OUTSIDE_PLAN; warnings never change the verdict."""
    failed = [f for f in findings if f.status is Status.FAIL]
    if any(f.spec.breaks is Breaks.OUTSIDE_PLAN for f in failed):
        return QcVerdict.OUTSIDE_PLAN
    if failed or any(f.status is Status.SKIPPED for f in findings):  # pragma: no cover
        raise RuntimeError("a LIVE check failed or was skipped without breaking the plan")
    return QcVerdict.IN_CONTROL


@dataclass(frozen=True)
class QcRun:
    """Everything decided about one QC run.

    Attributes:
        verdict: IN_CONTROL or OUTSIDE_PLAN.
        findings: One finding per LIVE check, in catalogue order.
        plan_id: Plan identifier.
        plan_revision: Plan revision.
        plan_fingerprint: Plan fingerprint.
        model_version: Version the live system reports.
        released_version: Version the ledger says is released.
        inputs: SHA-256 of every input file by role.
        bias: Mean of live minus expected score, or None if not measured.
        max_abs_deviation: Largest absolute difference, or None if not measured.
        rejections: Multirule rules that rejected the run.
        warnings: Multirule rules that warned.
        z: Standardised bias, or None before the baseline is complete.
        history: Earlier runs of this version, oldest first.
        run_at: Time of the run.
        ledger_entries_before: Ledger entries the history was read from.
        tool_version: Version of this package.
    """

    verdict: QcVerdict
    findings: tuple[Finding, ...]
    plan_id: str
    plan_revision: int
    plan_fingerprint: str
    model_version: str
    released_version: str
    inputs: dict[str, str]
    bias: float | None
    max_abs_deviation: float | None
    rejections: tuple[str, ...]
    warnings: tuple[str, ...]
    z: float | None
    history: tuple[QcHistoryRun, ...]
    run_at: dt.datetime
    ledger_entries_before: int = 0
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
            "kind": QC_KIND,
            "verdict": self.verdict.value,
            "exit_code": int(self.exit_code),
            "plan": {
                "id": self.plan_id,
                "revision": self.plan_revision,
                "fingerprint": self.plan_fingerprint,
            },
            "model_version": self.model_version,
            "released_version": self.released_version,
            "run_at": self.run_at.isoformat(),
            "inputs": dict(self.inputs),
            "qc": json_safe(
                {
                    "bias": self.bias,
                    "max_abs_deviation": self.max_abs_deviation,
                    "z": self.z,
                    "rejections": list(self.rejections),
                    "warnings": list(self.warnings),
                }
            ),
            "history": [
                {
                    "seq": run.seq,
                    "recorded_at": run.recorded_at.isoformat(),
                    "bias": run.bias,
                    "in_control": run.in_control,
                }
                for run in self.history
            ],
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


def released_version(plan: ChangePlan, entries: Sequence[dict[str, Any]]) -> str:
    """The latest version with a release record, or the anchor version when there is none."""
    released = [e["candidate_version"] for e in entries if e.get("kind") == "release"]
    return released[-1] if released else plan.anchor_version


def qc_history(entries: Sequence[dict[str, Any]], version: str) -> tuple[QcHistoryRun, ...]:
    """Earlier measured QC runs of ``version``, oldest first."""
    runs = []
    for entry in entries:
        if entry.get("kind") != QC_KIND or entry.get("model_version") != version:
            continue
        bias = (entry.get("qc") or {}).get("bias")
        if not isinstance(bias, int | float) or isinstance(bias, bool):
            continue
        runs.append(
            QcHistoryRun(
                seq=int(entry["seq"]),
                recorded_at=dt.datetime.fromisoformat(entry["recorded_at"]),
                bias=float(bias),
                in_control=entry.get("verdict") == QcVerdict.IN_CONTROL.value,
            )
        )
    return tuple(runs)


def require_qc(plan: ChangePlan) -> DeploymentQC:
    """The plan's deployment QC block.

    Raises:
        InputError: If the plan has none.
    """
    if plan.deployment_qc is None:
        raise InputError("the plan has no deployment_qc block; create one with medagentrx qc init")
    return plan.deployment_qc


def run_qc(
    *,
    plan: str | Path,
    scores: str | Path,
    expected: str | Path,
    model_version: str,
    entries: Sequence[dict[str, Any]] = (),
    control_inputs: str | Path | None = None,
    now: dt.datetime | None = None,
    limits: Limits | None = None,
    base: Path | None = None,
) -> QcRun:
    """Judge one QC run of the live system against the plan.

    Args:
        plan: ``change-plan.yaml`` with a ``deployment_qc`` block.
        scores: Scores of the live system on the control set.
        expected: Expected scores of ``model_version`` on the control set.
        model_version: Version the live system reports it is running.
        entries: Verified ledger entries, for the released version and run history.
        control_inputs: The raw control file, to check it against the plan.
        now: Time of the run. Defaults to the current UTC time.
        limits: Input size limits.
        base: Directory input symlinks may point into.

    Raises:
        PlanError: If the plan is invalid.
        InputError: If the plan has no QC block or an input file is invalid.
    """
    now = now or dt.datetime.now(dt.UTC)
    change_plan = load_plan(plan)
    qc = require_qc(change_plan)
    live = load_scores(scores, limits=limits, base=base)
    reference = load_scores(expected, limits=limits, base=base)
    inputs = {
        "plan": sha256_file(resolve_input(plan, base=base)),
        "scores": sha256_file(resolve_input(scores, base=base)),
        "expected": sha256_file(resolve_input(expected, base=base)),
    }
    if control_inputs is not None:
        inputs["control_inputs"] = sha256_file(resolve_input(control_inputs, base=base))
    ctx = QcContext(
        plan=change_plan,
        plan_fingerprint=plan_fingerprint(change_plan),
        qc=qc,
        model_version=model_version,
        released_version=released_version(change_plan, entries),
        live=live,
        expected=reference,
        live_sha256=inputs["scores"],
        expected_sha256=inputs["expected"],
        control_inputs_sha256=inputs.get("control_inputs"),
        history=qc_history(entries, model_version),
        now=now,
    )
    findings: list[Finding] = []
    for spec in catalogue(QC_FAMILIES):
        finding = spec.run(ctx)
        findings.append(finding)
        if finding.status is Status.FAIL and spec.check_id in ("LIVE-001", "LIVE-002"):
            ctx.blockers.append(spec.check_id)
    measured = ctx.measurement_blocker is None
    multirule = next(f for f in findings if f.check_id == "LIVE-004")
    tolerance = next(f for f in findings if f.check_id == "LIVE-003")
    notes: list[str] = []
    if multirule.status is Status.NOT_APPLICABLE:
        notes.append(multirule.message)
    return QcRun(
        verdict=decide_qc(findings),
        findings=tuple(findings),
        plan_id=change_plan.plan.id,
        plan_revision=change_plan.plan.revision,
        plan_fingerprint=ctx.plan_fingerprint,
        model_version=model_version,
        released_version=ctx.released_version,
        inputs=inputs,
        bias=run_bias(ctx) if measured else None,
        max_abs_deviation=tolerance.details.get("max_abs_deviation") if measured else None,
        rejections=tuple(multirule.details.get("rejections", ())),
        warnings=tuple(multirule.details.get("warnings", ())),
        z=multirule.details.get("z"),
        history=ctx.history,
        run_at=now,
        ledger_entries_before=len(entries),
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class QcInit:
    """Fingerprints for a plan's ``deployment_qc`` block.

    Attributes:
        control_inputs_sha256: SHA-256 of the raw control file.
        control_ids_fingerprint: Fingerprint of the control ids.
        version: The version whose expected scores were given.
        expected_sha256: SHA-256 of that version's expected score file.
        records: Number of control records.
        checked_against: Files the control ids were checked to be disjoint from.
    """

    control_inputs_sha256: str
    control_ids_fingerprint: str
    version: str
    expected_sha256: str
    records: int
    checked_against: tuple[str, ...]


def qc_init(
    *,
    control_inputs: str | Path,
    scores: str | Path,
    version: str,
    test_set: str | Path | None = None,
    manifest: str | Path | None = None,
    plan: str | Path | None = None,
    limits: Limits | None = None,
    base: Path | None = None,
) -> QcInit:
    """Fingerprint the control set and a version's expected scores on it.

    The control ids must be disjoint from the locked test set and from the
    training manifest, when they are given. With ``plan``, the control set
    must be the one its ``deployment_qc`` block already locks.

    Raises:
        InputError: If a file is invalid, the score file does not cover exactly
            the control ids, the control set overlaps the test set or the
            training data, or it differs from the plan's control set.
    """
    ids = load_row_ids(control_inputs, limits=limits, base=base)
    expected = load_scores(scores, limits=limits, base=base)
    fingerprint = id_fingerprint(ids)
    if id_fingerprint(expected.row_id.tolist()) != fingerprint:
        missing = sorted(set(ids) - set(expected.row_id.tolist()))
        extra = sorted(set(expected.row_id.tolist()) - set(ids))
        raise InputError(
            f"{expected.source}: the score file does not cover exactly the control ids",
            [f"{len(missing)} control ids without a score", f"{len(extra)} scores for other ids"],
        )
    checked: list[str] = []
    control = set(ids)
    if test_set is not None:
        test_ids = set(load_predictions(test_set, limits=limits, base=base).row_id.tolist())
        _require_disjoint(control, test_ids, "the locked test set")
        checked.append("locked test set")
    if manifest is not None:
        train_ids = set(load_row_ids(manifest, limits=limits, base=base))
        _require_disjoint(control, train_ids, "the training manifest")
        checked.append("training manifest")
    inputs_sha256 = sha256_file(resolve_input(control_inputs, base=base))
    if plan is not None:
        locked = require_qc(load_plan(plan))
        if (locked.control_ids_fingerprint, locked.control_inputs_sha256) != (
            fingerprint,
            inputs_sha256,
        ):
            raise InputError("the control file differs from the one the plan locks")
    return QcInit(
        control_inputs_sha256=inputs_sha256,
        control_ids_fingerprint=fingerprint,
        version=version,
        expected_sha256=sha256_file(resolve_input(scores, base=base)),
        records=len(ids),
        checked_against=tuple(checked),
    )


def _require_disjoint(control: set[str], other: set[str], name: str) -> None:
    shared = sorted(control & other)
    if shared:
        shown = ", ".join(repr(i) for i in shared[:5])
        raise InputError(
            f"{len(shared)} control ids also appear in {name} ({shown}); "
            "control records must never be used for training or testing"
        )


def qc_block_yaml(init: QcInit, *, tolerance: float = 1.0e-6) -> str:
    """A ready ``deployment_qc`` block for ``change-plan.yaml``."""
    return (
        "deployment_qc:                 # control samples for the live system\n"
        f'  control_inputs_sha256: "{init.control_inputs_sha256}"\n'
        f'  control_ids_fingerprint: "{init.control_ids_fingerprint}"\n'
        "  expected_scores:              # one entry per released version\n"
        f'    "{init.version}": "{init.expected_sha256}"\n'
        f"  tolerance: {{absolute: {tolerance:.1e}}}  # largest per-record difference\n"
        "  rules: [1_2s, 1_3s, 2_2s, R_4s, 10_x]\n"
        "  sd: null                     # or a number; null estimates it from baseline runs\n"
        "  baseline_runs: 20\n"
        '  schedule: "daily"            # documentation only\n'
    )


def qc_entry_yaml(init: QcInit) -> str:
    """The ``expected_scores`` line to add for a newly released version."""
    return f'    "{init.version}": "{init.expected_sha256}"\n'

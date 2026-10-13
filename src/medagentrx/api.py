# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Python API: check one update and record it, as ``medagentrx check`` does.

from medagentrx import check, Verdict

result = check(plan="change-plan.yaml", candidate="cand.parquet",
               previous="prev.parquet", anchor="anchor.parquet",
               manifest="train_manifest.parquet", model_meta="model.yaml",
               ledger="ledger.jsonl", out="report/")
assert result.verdict is Verdict.ACCEPTED
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medagentrx.engine import Evaluation, Verdict, evaluate
from medagentrx.errors import PlanError
from medagentrx.io.limits import Limits
from medagentrx.ledger import append, exclusive, load_history, read_entries, signing_policy
from medagentrx.plan import load_plan
from medagentrx.report.writer import FORMATS, write_reports
from medagentrx.stats.bootstrap import DEFAULT_REPLICATES


@dataclass(frozen=True)
class CheckResult:
    """Outcome of ``check``.

    Attributes:
        evaluation: Every finding and number behind the verdict.
        ledger_entry: The entry written to the ledger, or None for an invalid plan.
        reports: Written report files by format.
    """

    evaluation: Evaluation
    ledger_entry: dict[str, Any] | None
    reports: dict[str, Path] = field(default_factory=dict)

    @property
    def verdict(self) -> Verdict:
        """ACCEPTED, FAILED or OUTSIDE_PLAN."""
        return self.evaluation.verdict

    @property
    def exit_code(self) -> int:
        """0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN."""
        return int(self.evaluation.exit_code)


def check(
    *,
    plan: str | Path,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    manifest: str | Path,
    model_meta: str | Path,
    ledger: str | Path,
    out: str | Path,
    seed: int = 0,
    n_replicates: int = DEFAULT_REPLICATES,
    formats: Iterable[str] = tuple(FORMATS),
    limits: Limits | None = None,
    signing_key: str | Path | None = None,
) -> CheckResult:
    """Check one update against its plan, record it in the ledger and write reports.

    The ledger is locked from reading its budgets until the new entry is
    written. An invalid plan gives OUTSIDE_PLAN and is not recorded. When the
    plan names a ledger signing key, ``signing_key`` must be that private key;
    the existing head is verified with it and the new head is signed.

    Raises:
        InputError: If an input file other than the plan is missing or invalid.
        LedgerError: If the ledger fails verification.
    """
    ledger_path = Path(ledger)
    try:
        change_plan = load_plan(plan)
    except PlanError:
        change_plan = None
    key = signing_policy(change_plan, Path(signing_key) if signing_key is not None else None)
    public_key = key.public_key() if key is not None else None
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(ledger_path):
        evaluation = evaluate(
            plan=plan,
            candidate=candidate,
            previous=previous,
            anchor=anchor,
            manifest=manifest,
            model_meta=model_meta,
            history=load_history(ledger_path, public_key=public_key),
            seed=seed,
            n_replicates=n_replicates,
            limits=limits,
        )
        entry = None
        if evaluation.plan_id is not None:
            entry = append(ledger_path, evaluation, already_locked=True, signing_key=key)
    reports = write_reports(
        Path(out), evaluation, formats=formats, entry=entry, entries=read_entries(ledger_path)
    )
    return CheckResult(evaluation=evaluation, ledger_entry=entry, reports=reports)

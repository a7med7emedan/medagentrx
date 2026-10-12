# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""The agent boundary: an approved plan as the leash on automated retraining.

AutoML loops and coding agents now retrain models on their own. ``Guard``
lets them try candidates, but only inside the plan:

- ``allowed_modifications()`` lists the modifications the plan lets a
  pipeline or agent trigger without a person (``automatic: true``). Any
  other modification is refused before any data is read.
- Every ``submit`` that reaches the data spends one look from the locked
  test set's budget and is written to the decision ledger, so the budget
  stops an agent from trying candidates until one passes by chance.
- Guard looks spend no alpha and never count as releases. A release still
  needs a formal ``medagentrx check``.

In ``thresholdout`` mode the agent learns one bit per look. Following the
reusable holdout of Dwork et al. (2015), Laplace noise is added to the
margin of the primary AUROC test before it is compared with zero, and no
metric is returned. In ``exact`` mode the verdict and failed checks are
returned, for supervised use.

The ledger keeps the exact outcome for auditors. In thresholdout mode, keep
the ledger where the agent cannot read it.
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from medagentrx.engine import Evaluation, Verdict, evaluate, refused
from medagentrx.io.metadata import load_model_meta
from medagentrx.ledger import append, exclusive, load_history
from medagentrx.plan import load_plan
from medagentrx.plan.models import Modification
from medagentrx.stats._common import norm_ppf

Mode = Literal["thresholdout", "exact"]
DEFAULT_NOISE_SCALE = 1.0
"""Laplace scale on the z margin of the AUROC test, in standard error units."""

STATISTICAL_FAMILIES = ("PERF", "LIFE", "DOC")


@dataclass(frozen=True)
class Decision:
    """What the guard tells the agent.

    Attributes:
        allowed: True when the candidate may go forward to a formal check.
        reason: Short text without test-set metrics in thresholdout mode.
        looks_used: Looks at the locked test set used so far, including this one.
        looks_remaining: Looks still available under the plan.
        verdict: Exact verdict in exact mode; None in thresholdout mode.
        failed_checks: Failed checks in exact mode, or plan and data checks that
            refused the candidate in either mode.
    """

    allowed: bool
    reason: str
    looks_used: int
    looks_remaining: int
    verdict: Verdict | None = None
    failed_checks: tuple[str, ...] = field(default_factory=tuple)


class Guard:
    """Gate an agent's candidates against the approved change plan.

    Args:
        plan: ``change-plan.yaml``.
        ledger: Decision ledger shared with formal checks.
        mode: ``thresholdout`` (default) or ``exact``.
        previous: Predictions of the deployed version on the locked test set.
        anchor: Predictions of the authorised version. Defaults to ``previous``.
        noise_scale: Laplace scale for thresholdout answers.
        seed: Seed of the noise. Defaults to a fresh random seed, which the agent
            should not know.
        n_replicates: Bootstrap replicates for each look.
    """

    def __init__(
        self,
        plan: str | Path,
        ledger: str | Path,
        mode: Mode = "thresholdout",
        *,
        previous: str | Path,
        anchor: str | Path | None = None,
        noise_scale: float = DEFAULT_NOISE_SCALE,
        seed: int | None = None,
        n_replicates: int = 2000,
    ) -> None:
        if mode not in ("thresholdout", "exact"):
            raise ValueError(f"mode must be 'thresholdout' or 'exact', got {mode!r}")
        if noise_scale <= 0:
            raise ValueError("noise_scale must be positive")
        self.plan_path = Path(plan)
        self.ledger = Path(ledger)
        self.mode = mode
        self.previous = Path(previous)
        self.anchor = Path(anchor) if anchor is not None else Path(previous)
        self.noise_scale = noise_scale
        self.n_replicates = n_replicates
        self._rng = np.random.default_rng(secrets.randbits(64) if seed is None else seed)
        self.plan = load_plan(self.plan_path)

    def allowed_modifications(self) -> list[Modification]:
        """Modifications the plan lets a pipeline or agent trigger without a person."""
        return [m for m in self.plan.modifications if m.automatic]

    def submit(
        self,
        candidate: str | Path,
        model_meta: str | Path,
        *,
        manifest: str | Path,
        now: dt.datetime | None = None,
    ) -> Decision:
        """Evaluate one candidate, record the look and answer the agent."""
        now = now or dt.datetime.now(dt.UTC)
        meta = load_model_meta(model_meta)
        allowed_ids = [m.id for m in self.allowed_modifications()]
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(self.ledger):
            history = load_history(self.ledger)
            if meta.modification_id not in allowed_ids:
                listed = ", ".join(allowed_ids) or "none"
                evaluation = refused(
                    plan=self.plan,
                    meta=meta,
                    check_id="PLAN-002",
                    message=(
                        f"Modification {meta.modification_id!r} may not be made by an agent "
                        f"(allowed without a person: {listed})"
                    ),
                    history=history,
                    now=now,
                )
            else:
                evaluation = evaluate(
                    plan=self.plan_path,
                    candidate=candidate,
                    previous=self.previous,
                    anchor=self.anchor,
                    manifest=manifest,
                    model_meta=model_meta,
                    history=history,
                    n_replicates=self.n_replicates,
                    now=now,
                )
            append(self.ledger, evaluation, already_locked=True, kind="guard")
        return self._answer(evaluation, history.looks_used)

    def _answer(self, evaluation: Evaluation, looks_before: int) -> Decision:
        limit = self.plan.data_management.locked_test_set.max_evaluations
        used = looks_before + (1 if evaluation.touched_test_set else 0)
        remaining = max(limit - used, 0)
        if evaluation.verdict is Verdict.OUTSIDE_PLAN:
            failed = tuple(evaluation.failed_checks)
            return Decision(
                allowed=False,
                reason="Refused: outside the plan (" + ", ".join(failed) + ")",
                looks_used=used,
                looks_remaining=remaining,
                verdict=evaluation.verdict if self.mode == "exact" else None,
                failed_checks=failed,
            )
        if self.mode == "exact":
            ok = evaluation.verdict is Verdict.ACCEPTED
            failed = tuple(evaluation.failed_checks)
            reason = "Meets the plan's criteria" if ok else "Fails: " + ", ".join(failed)
            return Decision(ok, reason, used, remaining, evaluation.verdict, failed)
        ok = self._noisy_pass(evaluation)
        reason = (
            "Passes the plan's criteria (noisy answer)"
            if ok
            else "Does not pass the plan's criteria (noisy answer)"
        )
        return Decision(ok, reason, used, remaining)

    def _noisy_pass(self, evaluation: Evaluation) -> bool:
        """Thresholdout-style answer: noise on the AUROC margin, exact on the rest."""
        others_pass = all(
            f.status.value != "fail"
            for f in evaluation.findings
            if f.check_id.split("-")[0] in STATISTICAL_FAMILIES and f.check_id != "PERF-001"
        ) and not [f for f in evaluation.failed_checks if f.split("-")[0] in ("PLAN", "DATA")]
        perf = evaluation.finding("PERF-001")
        tests = perf.details.get("tests", {})
        margin = 0.0
        if tests:
            margin = min(
                (t["delta"] + t["margin"]) / t["se"] - norm_ppf(1.0 - t["alpha"])
                if t["se"] > 0
                else (np.inf if t["non_inferior"] else -np.inf)
                for t in tests.values()
            )
        elif perf.status.value == "fail":  # pragma: no cover  # failures always carry tests
            margin = -np.inf
        noisy = margin + float(self._rng.laplace(0.0, self.noise_scale))
        return bool(others_pass and noisy > 0.0)

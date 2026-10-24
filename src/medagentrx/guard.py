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

In ``thresholdout`` mode the agent learns one bit per look, about the
plan's statistical criteria taken together. Every criterion is put on one
scale (see ``medagentrx.slack``), the smallest slack is taken, and Laplace
noise is added once before it is compared with zero. No metric is returned.

If the agent also passes predictions on its own validation data, the guard
runs Thresholdout (Dwork et al. 2015). When the validation result agrees with
the locked test set, within a noisy threshold, the answer comes from the
validation data and reveals almost nothing about the test set. Otherwise the
noisy test-set answer is given. Every look still counts against the plan's
budget, because the plan's budget is a regulatory limit, not a privacy one.

In ``exact`` mode the verdict and failed checks are returned, for supervised
use.

The ledger keeps the exact outcome and what the agent was told, for
auditors. In thresholdout mode, keep the ledger where the agent cannot read
it.
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from medagentrx.engine import Evaluation, Verdict, evaluate, refused, statistical_findings
from medagentrx.io.metadata import ModelMeta, load_model_meta
from medagentrx.ledger import (
    append,
    append_qc,
    exclusive,
    load_history,
    read_entries,
    signing_policy,
)
from medagentrx.plan import load_plan
from medagentrx.plan.models import Modification
from medagentrx.qc import QcRun, run_qc
from medagentrx.slack import STATISTICAL_CHECKS, aggregate, aggregate_against, slacks
from medagentrx.stats.alpha import next_alpha

Mode = Literal["thresholdout", "exact"]
Source = Literal["exact", "holdout", "validation"]
DEFAULT_NOISE_SCALE = 0.5
"""Laplace scale on the aggregate slack, in standard error units."""

DEFAULT_THRESHOLD = 4.0
"""Thresholdout threshold on the gap between validation and test-set slack.

Four times the noise scale, the ratio of the worked example in Dwork et al.
(2015), so that noise rarely hides a real disagreement.
"""


@dataclass(frozen=True)
class Validation:
    """Predictions on the agent's own validation data, in the prediction file format.

    Attributes:
        candidate: The candidate's predictions, with the plan's subgroup columns.
        previous: The deployed version's predictions on the same rows.
        anchor: The authorised version's predictions. Defaults to ``previous``.
    """

    candidate: str | Path
    previous: str | Path
    anchor: str | Path | None = None


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
        noise_scale: Laplace scale for thresholdout answers, in standard error units.
        threshold: Thresholdout threshold on the validation and test-set gap.
            Defaults to four times ``noise_scale``.
        seed: Seed of the noise. Defaults to a fresh random seed, which the agent
            should not know.
        n_replicates: Bootstrap replicates for each look.
        signing_key: Ledger signing key, required when the plan names one. Run the
            guard in a process the agent cannot read when using it.
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
        threshold: float | None = None,
        seed: int | None = None,
        n_replicates: int = 2000,
        signing_key: str | Path | None = None,
    ) -> None:
        if mode not in ("thresholdout", "exact"):
            raise ValueError(f"mode must be 'thresholdout' or 'exact', got {mode!r}")
        if noise_scale <= 0:
            raise ValueError("noise_scale must be positive")
        if threshold is None:
            threshold = DEFAULT_THRESHOLD * noise_scale
        if threshold < 0:
            raise ValueError("threshold must not be negative")
        self.plan_path = Path(plan)
        self.ledger = Path(ledger)
        self.mode = mode
        self.previous = Path(previous)
        self.anchor = Path(anchor) if anchor is not None else Path(previous)
        self.noise_scale = noise_scale
        self.threshold = threshold
        self.n_replicates = n_replicates
        self._rng = np.random.default_rng(secrets.randbits(64) if seed is None else seed)
        self._gamma = self._laplace(2.0)
        self.plan = load_plan(self.plan_path)
        self._key = signing_policy(self.plan, Path(signing_key) if signing_key else None)

    def allowed_modifications(self) -> list[Modification]:
        """Modifications the plan lets a pipeline or agent trigger without a person."""
        return [m for m in self.plan.modifications if m.automatic]

    def submit(
        self,
        candidate: str | Path,
        model_meta: str | Path,
        *,
        manifest: str | Path,
        validation: Validation | None = None,
        now: dt.datetime | None = None,
    ) -> Decision:
        """Evaluate one candidate, record the look and answer the agent.

        Args:
            candidate: Candidate predictions on the locked test set.
            model_meta: ``model.yaml`` of the candidate.
            manifest: Training data manifest of the candidate.
            validation: Predictions on the agent's own validation data. In
                thresholdout mode they let the guard answer from them when they
                agree with the locked test set.
            now: Evaluation time. Defaults to the current UTC time.
        """
        now = now or dt.datetime.now(dt.UTC)
        meta = load_model_meta(model_meta)
        allowed_ids = [m.id for m in self.allowed_modifications()]
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(self.ledger):
            public_key = self._key.public_key() if self._key is not None else None
            history = load_history(self.ledger, public_key=public_key)
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
            decision, source = self._answer(evaluation, history.looks_used, meta, validation)
            append(
                self.ledger,
                evaluation,
                already_locked=True,
                kind="guard",
                signing_key=self._key,
                answer={"mode": self.mode, "allowed": decision.allowed, "source": source},
            )
        return decision

    def qc(
        self,
        scores: str | Path,
        expected: str | Path,
        *,
        model_version: str,
        control_inputs: str | Path | None = None,
        now: dt.datetime | None = None,
    ) -> QcRun:
        """Run deployment QC on the live system and record it in the guard's ledger.

        An agent that operates the deployment can check, on a schedule, that the
        live stack still reproduces the released version's control scores. The
        exact QC result is returned; QC runs never touch the locked test set, so
        nothing about it needs hiding.

        Args:
            scores: Live scores on the plan's control set.
            expected: Expected scores of ``model_version`` on the control set.
            model_version: Version the live system reports it is running.
            control_inputs: The raw control file, to check it against the plan.
            now: Time of the run. Defaults to the current UTC time.
        """
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(self.ledger):
            public_key = self._key.public_key() if self._key is not None else None
            load_history(self.ledger, public_key=public_key)
            run = run_qc(
                plan=self.plan_path,
                scores=scores,
                expected=expected,
                model_version=model_version,
                entries=read_entries(self.ledger),
                control_inputs=control_inputs,
                now=now,
            )
            append_qc(self.ledger, run, already_locked=True, signing_key=self._key)
        return run

    def _answer(
        self,
        evaluation: Evaluation,
        looks_before: int,
        meta: ModelMeta,
        validation: Validation | None,
    ) -> tuple[Decision, Source]:
        limit = self.plan.data_management.locked_test_set.max_evaluations
        used = looks_before + (1 if evaluation.touched_test_set else 0)
        remaining = max(limit - used, 0)
        if evaluation.verdict is Verdict.OUTSIDE_PLAN:
            failed = tuple(evaluation.failed_checks)
            decision = Decision(
                allowed=False,
                reason="Refused: outside the plan (" + ", ".join(failed) + ")",
                looks_used=used,
                looks_remaining=remaining,
                verdict=evaluation.verdict if self.mode == "exact" else None,
                failed_checks=failed,
            )
            return decision, "exact"
        if self.mode == "exact":
            ok = evaluation.verdict is Verdict.ACCEPTED
            failed = tuple(evaluation.failed_checks)
            reason = "Meets the plan's criteria" if ok else "Fails: " + ", ".join(failed)
            return Decision(ok, reason, used, remaining, evaluation.verdict, failed), "exact"
        # Failures that do not read the test-set labels, such as the model card, are exact.
        other = tuple(c for c in evaluation.failed_checks if c not in STATISTICAL_CHECKS)
        if other:
            reason = "Fails checks that do not use the test set: " + ", ".join(other)
            return Decision(False, reason, used, remaining, failed_checks=other), "exact"
        ok, source = self._thresholdout(evaluation, meta, validation)
        reason = (
            "Passes the plan's criteria (noisy answer)"
            if ok
            else "Does not pass the plan's criteria (noisy answer)"
        )
        return Decision(ok, reason, used, remaining), source

    def _laplace(self, multiple: float) -> float:
        return float(self._rng.laplace(0.0, multiple * self.noise_scale))

    def _thresholdout(
        self, evaluation: Evaluation, meta: ModelMeta, validation: Validation | None
    ) -> tuple[bool, Source]:
        """One noisy bit for all statistical criteria together.

        Without validation data this is the noisy test-set answer. With them,
        it follows Thresholdout: answer from the validation data unless they
        differ from the test set by more than a noisy threshold.
        """
        holdout = slacks(evaluation.findings)
        test_slack = aggregate(holdout)
        if validation is not None and evaluation.alpha_state is not None:
            found = statistical_findings(
                plan=self.plan,
                meta=meta,
                candidate=validation.candidate,
                previous=validation.previous,
                anchor=validation.anchor or validation.previous,
                alpha=next_alpha(evaluation.alpha_state),
                check_ids=STATISTICAL_CHECKS,
                seed=evaluation.seed,
                n_replicates=self.n_replicates,
            )
            validation_slack = aggregate_against(slacks(found), holdout)
            gap = abs(test_slack - validation_slack)
            if not gap > self.threshold + self._gamma + self._laplace(4.0):
                return bool(validation_slack > 0.0), "validation"
            self._gamma = self._laplace(2.0)
        return bool(test_slack + self._laplace(1.0) > 0.0), "holdout"

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Everything the checks read, gathered once per evaluation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from functools import cached_property

from medagentrx.history import History
from medagentrx.io.manifest import Manifest
from medagentrx.io.metadata import ModelMeta
from medagentrx.io.predictions import Predictions, RowMismatch
from medagentrx.plan.models import ChangePlan
from medagentrx.stats.alpha import AlphaState
from medagentrx.stats.delong import AucCovariance, delong


@dataclass(frozen=True)
class Versions:
    """Candidate, previous and anchor predictions aligned on the same rows."""

    candidate: Predictions
    previous: Predictions
    anchor: Predictions


@dataclass
class Context:
    """Inputs and shared results for one evaluation.

    Attributes:
        plan: The validated change plan.
        plan_fingerprint: Fingerprint of the plan.
        meta: Candidate model metadata.
        candidate: Candidate predictions as loaded.
        test_fingerprint: Fingerprint of the candidate's test rows and labels.
        versions: Aligned predictions, or None if rows or labels differ.
        mismatches: Row mismatch per comparator file, empty when aligned.
        manifest: Training data manifest.
        manifest_sha256: SHA-256 of the manifest file.
        test_features: Feature columns present in both the manifest and the test file.
        history: Budgets used by earlier evaluations.
        alpha_state: Alpha accounting before this evaluation.
        alpha: One-sided level for this evaluation, or None if the budget is exhausted.
        seed: Seed for every resampling step.
        n_replicates: Bootstrap replicates.
        now: Time of the evaluation.
    """

    plan: ChangePlan
    plan_fingerprint: str
    meta: ModelMeta
    candidate: Predictions
    test_fingerprint: str
    versions: Versions | None
    mismatches: dict[str, RowMismatch]
    manifest: Manifest
    manifest_sha256: str
    test_features: dict[str, tuple[str, ...]]
    history: History
    alpha_state: AlphaState
    alpha: float | None
    seed: int
    n_replicates: int
    now: dt.datetime
    notes: list[str] = field(default_factory=list)

    @property
    def test_set_is_locked(self) -> bool:
        """True when the candidate's test rows match the plan's fingerprint."""
        return self.test_fingerprint == self.plan.data_management.locked_test_set.sha256

    @property
    def performance_blocker(self) -> str | None:
        """Why performance cannot be assessed, or None when it can."""
        if not self.test_set_is_locked:
            return "the test set is not the locked test set (DATA-001)"
        if self.versions is None:
            return "prediction files do not share the same rows and labels (DATA-001)"
        if self.alpha is None:
            return "the alpha budget is exhausted (LIFE-002)"
        return None

    def require_versions(self) -> Versions:
        """Aligned predictions. Only call after ``performance_blocker`` is None."""
        if self.versions is None:  # pragma: no cover  # guarded by performance_blocker
            raise RuntimeError("predictions are not aligned")
        return self.versions

    def require_alpha(self) -> float:
        """Level for this evaluation. Only call after ``performance_blocker`` is None."""
        if self.alpha is None:  # pragma: no cover  # guarded by performance_blocker
            raise RuntimeError("alpha budget exhausted")
        return self.alpha

    @cached_property
    def aucs(self) -> AucCovariance:
        """DeLong AUROC and covariance of candidate, previous and anchor, in that order."""
        v = self.require_versions()
        return delong(v.candidate.y_true, v.candidate.y_score, v.previous.y_score, v.anchor.y_score)

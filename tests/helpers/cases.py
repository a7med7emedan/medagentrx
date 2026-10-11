# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Small synthetic evaluation cases for engine and check tests.

The candidate's logit is the true risk, so it is calibrated by construction.
Previous and anchor versions add noise to that logit, so they rank worse.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
import yaml

from medagentrx.io.fingerprint import fingerprint_file
from tests.conftest import EXAMPLE_PLAN, write_table

INTENDED_USE = "b3bf70048c7ee76c2a16884829d284f27b32795bea5c63d734aafc8fdd0ceeaa"


class CaseInputs(TypedDict):
    """Keyword arguments of ``evaluate`` naming the input files."""

    plan: Path
    candidate: Path
    previous: Path
    anchor: Path
    manifest: Path
    model_meta: Path


@dataclass(frozen=True)
class Case:
    """Paths of one evaluation case."""

    plan: Path
    candidate: Path
    previous: Path
    anchor: Path
    manifest: Path
    model_meta: Path

    def kwargs(self) -> CaseInputs:
        return {
            "plan": self.plan,
            "candidate": self.candidate,
            "previous": self.previous,
            "anchor": self.anchor,
            "manifest": self.manifest,
            "model_meta": self.model_meta,
        }


def _expit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def make_case(
    root: Path,
    *,
    n: int = 4000,
    seed: int = 7,
    previous_noise: float = 0.8,
    anchor_noise: float | None = None,
    candidate_noise: float = 0.0,
    candidate_scale: float = 1.0,
    harm_site: str | None = None,
    leak: int = 0,
    plan_edit: Callable[[dict[str, Any]], None] | None = None,
    meta_edit: Callable[[dict[str, Any]], None] | None = None,
    manifest_edit: Callable[[dict[str, list[object]]], None] | None = None,
    test_extra: dict[str, list[object]] | None = None,
) -> Case:
    """Write a complete case into ``root`` and return its paths."""
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    truth = -1.8 + 1.4 * x
    y = (rng.random(n) < _expit(truth)).astype(int)
    sex = rng.choice(["F", "M"], size=n)
    age_band = rng.choice(["18-44", "45-64", "65+"], size=n)
    site = rng.choice(["A", "B", "C"], size=n)
    row_id: list[object] = [f"T{i:05d}" for i in range(n)]
    patient: list[object] = [f"P{i:05d}" for i in range(n)]

    cand_logit = (
        truth + rng.normal(0, candidate_noise, n) if candidate_noise else truth
    ) / candidate_scale
    if harm_site is not None:
        members = site == harm_site
        cand_logit = np.where(members, truth + rng.normal(0, 2.5, n), cand_logit)
    prev_logit = truth + rng.normal(0, previous_noise, n)
    anchor_logit = prev_logit if anchor_noise is None else truth + rng.normal(0, anchor_noise, n)

    def preds(name: str, logit: np.ndarray, extra: bool) -> Path:
        cols: dict[str, list[object]] = {
            "row_id": row_id,
            "y_true": y.tolist(),
            "y_score": np.round(_expit(logit), 12).tolist(),
        }
        if extra:
            cols |= {
                "patient_id": patient,
                "sex": sex.tolist(),
                "age_band": age_band.tolist(),
                "site": site.tolist(),
            }
            cols |= test_extra or {}
        return write_table(root / f"{name}.csv", cols)

    candidate = preds("candidate", cand_logit, extra=True)
    previous = preds("previous", prev_logit, extra=False)
    anchor = preds("anchor", anchor_logit, extra=False)

    m = 3000
    train_ids: list[object] = [f"R{i:05d}" for i in range(m)]
    train_patients: list[object] = [f"Q{i:05d}" for i in range(m)]
    train: dict[str, list[object]] = {
        "row_id": train_ids,
        "patient_id": train_patients,
        "age": rng.integers(18, 95, m).tolist(),
        "site": rng.choice(["A", "B", "C"], m).tolist(),
        "admission_date": [f"2024-{1 + i % 12:02d}-{1 + i % 28:02d}" for i in range(m)],
    }
    for i in range(leak):
        train["patient_id"][i] = patient[i]
    if manifest_edit:
        manifest_edit(train)
    manifest = write_table(root / "manifest.csv", train)

    plan_data = yaml.safe_load(EXAMPLE_PLAN.read_text(encoding="utf-8"))
    plan_data["data_management"]["locked_test_set"]["sha256"] = fingerprint_file(candidate)
    if plan_edit:
        plan_edit(plan_data)
    plan = root / "change-plan.yaml"
    plan.write_text(yaml.safe_dump(plan_data, sort_keys=False), encoding="utf-8")

    meta_data: dict[str, Any] = {
        "version": "2.1.0",
        "previous_version": "2.0.0",
        "modification_id": "M1",
        "architecture_sha256": "a" * 64,
        "intended_use_sha256": INTENDED_USE,
        "trained_at": "2026-04-01T10:00:00+00:00",
        "training_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    if meta_edit:
        meta_edit(meta_data)
    model_meta = root / "model.yaml"
    model_meta.write_text(yaml.safe_dump(meta_data, sort_keys=False), encoding="utf-8")
    return Case(plan, candidate, previous, anchor, manifest, model_meta)

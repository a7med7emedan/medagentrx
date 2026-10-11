# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Planted scenarios: the tool's self-test on synthetic data.

Each scenario writes a complete case (plan, prediction files, training
manifest, model metadata) and runs it through the engine and a fresh
ledger. It must produce exactly its expected verdict and failing checks.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from medagentrx.demo.cohort import (
    Cohort,
    FloatArray,
    make_cohort,
    noisy_logit,
    recalibrated,
    sigma_for_auc,
)
from medagentrx.demo.plan import demo_plan
from medagentrx.engine import Evaluation, Verdict, evaluate
from medagentrx.io.fingerprint import fingerprint_rows
from medagentrx.ledger import append, exclusive, load_history
from medagentrx.stats.delong import auc_fast

START = dt.datetime(2026, 4, 15, 9, 0, tzinfo=dt.UTC)
PREVIOUS_AUC = 0.770
SCORE_DECIMALS = 6
INTENDED_USE_TEXT = (resources.files("medagentrx.demo") / "intended-use.txt").read_bytes()
INTENDED_USE_SHA256 = hashlib.sha256(INTENDED_USE_TEXT).hexdigest()


@dataclass(frozen=True)
class Step:
    """One evaluation in a scenario and what it must give."""

    candidate_version: str
    expected: Verdict
    expected_failed: tuple[str, ...]
    expected_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    """A planted property and the outcome it must produce."""

    name: str
    planted: str
    steps: tuple[Step, ...]
    build: Callable[[Cohort, Path], list[dict[str, Any]]]


@dataclass
class StepResult:
    """What one step actually gave."""

    step: Step
    evaluation: Evaluation

    @property
    def ok(self) -> bool:
        """True when verdict, failed checks and warnings are exactly as expected."""
        warnings = tuple(f.check_id for f in self.evaluation.findings if f.status.value == "warn")
        return (
            self.evaluation.verdict is self.step.expected
            and tuple(self.evaluation.failed_checks) == self.step.expected_failed
            and warnings == self.step.expected_warnings
        )


@dataclass
class ScenarioResult:
    """All steps of one scenario."""

    scenario: Scenario
    directory: Path
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every step matched."""
        return len(self.steps) == len(self.scenario.steps) and all(s.ok for s in self.steps)


# Writing files --------------------------------------------------------------------------


def _probabilities(y: np.ndarray, logit: FloatArray) -> list[float]:
    rounded: list[float] = np.round(recalibrated(y, logit), SCORE_DECIMALS).tolist()
    return rounded


def write_parquet(path: Path, columns: dict[str, list[object]]) -> Path:
    """Write columns as Parquet without timestamps, so output depends only on the data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path, compression="zstd", store_schema=True)
    return path


def _predictions(
    cohort: Cohort, path: Path, scores: list[float], *, full: bool, labels: list[int] | None = None
) -> Path:
    columns: dict[str, list[object]] = {
        "row_id": cohort.test["row_id"],
        "y_true": list(labels if labels is not None else cohort.y.tolist()),
        "y_score": list(scores),
    }
    if full:
        for name in ("patient_id", "sex", "age", "age_band", "site", "lactate"):
            columns[name] = cohort.test[name]
    return write_parquet(path, columns)


def _manifest(
    cohort: Cohort, path: Path, edit: Callable[[dict[str, list[object]]], None] | None = None
) -> Path:
    train = {name: list(values) for name, values in cohort.train.items()}
    if edit:
        edit(train)
    return write_parquet(path, train)


def _meta(
    path: Path,
    *,
    version: str,
    previous: str,
    manifest: Path,
    modification: str = "M1",
    architecture: str = "1" * 64,
) -> Path:
    data = {
        "version": version,
        "previous_version": previous,
        "modification_id": modification,
        "architecture_sha256": architecture,
        "intended_use_sha256": INTENDED_USE_SHA256,
        "trained_at": "2026-04-01T08:00:00+00:00",
        "training_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def locked_fingerprint(cohort: Cohort) -> str:
    """Fingerprint of the cohort's true test rows and labels."""
    return fingerprint_rows([str(r) for r in cohort.test["row_id"]], cohort.y.tolist())


def _plan(path: Path, cohort: Cohort, edit: Callable[[dict[str, Any]], None] | None = None) -> Path:
    plan = demo_plan(
        test_set_sha256=locked_fingerprint(cohort), intended_use_sha256=INTENDED_USE_SHA256
    )
    if edit:
        edit(plan)
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    (path.parent / "intended-use.txt").write_bytes(INTENDED_USE_TEXT)
    return path


def _case(
    cohort: Cohort,
    root: Path,
    candidate_logit: FloatArray,
    *,
    previous_logit: FloatArray,
    anchor_logit: FloatArray | None = None,
    candidate_scores: list[float] | None = None,
    labels: list[int] | None = None,
    manifest_edit: Callable[[dict[str, list[object]]], None] | None = None,
    plan_edit: Callable[[dict[str, Any]], None] | None = None,
    modification: str = "M1",
    architecture: str = "1" * 64,
    version: str = "2.1.0",
    previous_version: str = "2.0.0",
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    y = cohort.y
    cand = candidate_scores if candidate_scores is not None else _probabilities(y, candidate_logit)
    candidate = _predictions(cohort, root / "candidate.parquet", cand, full=True, labels=labels)
    previous = _predictions(
        cohort,
        root / "previous.parquet",
        _probabilities(y, previous_logit),
        full=False,
        labels=labels,
    )
    anchor_scores = _probabilities(y, previous_logit if anchor_logit is None else anchor_logit)
    anchor = _predictions(cohort, root / "anchor.parquet", anchor_scores, full=False, labels=labels)
    manifest = _manifest(cohort, root / "train_manifest.parquet", manifest_edit)
    plan = _plan(root / "change-plan.yaml", cohort, plan_edit)
    meta = _meta(
        root / "model.yaml",
        version=version,
        previous=previous_version,
        manifest=manifest,
        modification=modification,
        architecture=architecture,
    )
    return {
        "plan": plan,
        "candidate": candidate,
        "previous": previous,
        "anchor": anchor,
        "manifest": manifest,
        "model_meta": meta,
    }


# Version builders ------------------------------------------------------------------------


def previous_logit(cohort: Cohort) -> FloatArray:
    """The authorised version 2.0.0, with AUROC near ``PREVIOUS_AUC``."""
    return noisy_logit(cohort, sigma_for_auc(cohort, PREVIOUS_AUC))


def improved_logit(cohort: Cohort, gain: float = 0.015) -> FloatArray:
    """A version better than 2.0.0 by ``gain`` AUROC."""
    return noisy_logit(cohort, sigma_for_auc(cohort, PREVIOUS_AUC + gain))


def _single(
    cohort: Cohort,
    root: Path,
    candidate_logit: FloatArray,
    **kwargs: Any,  # noqa: ANN401
) -> list[dict[str, Any]]:
    case = _case(cohort, root, candidate_logit, previous_logit=previous_logit(cohort), **kwargs)
    return [{"inputs": case, "now": START, "directory": root}]


def build_good_update(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Better AUROC, calibrated, no subgroup harm."""
    return _single(cohort, root, improved_logit(cohort))


def build_subgroup_harm(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Better at sites A and B; site C loses 0.06 AUROC."""
    prev = previous_logit(cohort)
    site = np.array(cohort.test["site"])
    harmed = site == "C"
    others = ~harmed
    gain = sigma_for_auc(cohort, auc_fast(cohort.y[others], prev[others]) + 0.04, members=others)
    loss = sigma_for_auc(cohort, auc_fast(cohort.y[harmed], prev[harmed]) - 0.06, members=harmed)
    candidate = cohort.truth + np.where(harmed, loss, gain) * cohort.noise
    return _single(cohort, root, candidate)


def build_miscalibrated(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Same ranking as version 2.0.0, but overconfident: calibration slope 0.6.

    The probabilities are stretched around a risk of 0.2, the middle of the
    plan's clinical thresholds, so decisions there barely change.
    """
    prev = previous_logit(cohort)
    calibrated = recalibrated(cohort.y, prev)
    pivot = float(np.log(0.2 / 0.8))
    stretched = pivot + (np.log(calibrated) - np.log1p(-calibrated) - pivot) / 0.6
    scores = np.round(1.0 / (1.0 + np.exp(-stretched)), SCORE_DECIMALS).tolist()
    return _single(cohort, root, prev, candidate_scores=scores)


def build_leaky_training(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """300 test patients also appear in the training manifest."""
    test_patients = cohort.test["patient_id"][:300]

    def leak(train: dict[str, list[object]]) -> None:
        train["patient_id"][:300] = test_patients

    return _single(cohort, root, improved_logit(cohort), manifest_edit=leak)


def build_test_set_tampered(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """40 labels in the locked test set have been edited in every prediction file."""
    labels = cohort.y.tolist()
    for i in range(40):
        labels[i * 97] = 1 - labels[i * 97]
    return _single(cohort, root, improved_logit(cohort), labels=labels)


def build_new_architecture(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """A new architecture, which the plan does not list as a modification."""
    return _single(
        cohort, root, improved_logit(cohort), modification="NEW-ARCH", architecture="2" * 64
    )


def build_out_of_scope_data(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """150 paediatric rows in the training data; the plan allows adults only."""

    def paediatric(train: dict[str, list[object]]) -> None:
        for i in range(150):
            train["age"][i * 199] = 2 + i % 16

    return _single(cohort, root, improved_logit(cohort), manifest_edit=paediatric)


BIO_CREEP_STEPS = 5
BIO_CREEP_DROP = 0.008
BIO_CREEP_BUDGET = 0.04


def _bio_creep_plan(plan: dict[str, Any]) -> None:
    plan["performance"]["criteria"][0]["vs"] = ["previous"]
    plan["performance"]["cumulative_drift"]["max_drop_vs_anchor"] = BIO_CREEP_BUDGET


def build_bio_creep(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Five quarterly updates, each 0.008 AUROC below the one before.

    Each is non-inferior to its predecessor. The plan's cumulative budget
    against the anchor is 0.04, which the fifth update breaks.
    """
    anchor = previous_logit(cohort)
    anchor_auc = auc_fast(cohort.y, anchor)
    versions = [anchor] + [
        noisy_logit(cohort, sigma_for_auc(cohort, anchor_auc - BIO_CREEP_DROP * k))
        for k in range(1, BIO_CREEP_STEPS + 1)
    ]
    steps = []
    for k in range(1, BIO_CREEP_STEPS + 1):
        directory = root / f"update-{k}"
        case = _case(
            cohort,
            directory,
            versions[k],
            previous_logit=versions[k - 1],
            anchor_logit=anchor,
            plan_edit=_bio_creep_plan,
            version=f"2.{k}.0",
            previous_version=f"2.{k - 1}.0",
        )
        steps.append(
            {"inputs": case, "now": START + dt.timedelta(days=92 * (k - 1)), "directory": directory}
        )
    return steps


UNDERPOWERED_ROWS = 4000


def build_underpowered(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """A smaller hospital: 4,000 test rows cannot reliably detect a 0.02 AUROC loss.

    The candidate is clearly better, so it is accepted, but with a power warning.
    """
    del cohort
    small = make_cohort(n_test=UNDERPOWERED_ROWS, n_train=6000, seed=7)
    prev = noisy_logit(small, sigma_for_auc(small, 0.72))
    case = _case(small, root, small.truth, previous_logit=prev)
    return [{"inputs": case, "now": START, "directory": root}]


ACCEPTED, FAILED, OUTSIDE = Verdict.ACCEPTED, Verdict.FAILED, Verdict.OUTSIDE_PLAN

SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario(
            "good-update",
            "Better AUROC, calibrated, no subgroup harm",
            (Step("2.1.0", ACCEPTED, ()),),
            build_good_update,
        ),
        Scenario(
            "subgroup-harm",
            "Overall better, one site drops 0.06",
            (Step("2.1.0", FAILED, ("PERF-005",)),),
            build_subgroup_harm,
        ),
        Scenario(
            "miscalibrated",
            "Same AUROC, slope 0.6",
            (Step("2.1.0", FAILED, ("PERF-003",)),),
            build_miscalibrated,
        ),
        Scenario(
            "leaky-training",
            "300 test patients in the training manifest",
            (Step("2.1.0", FAILED, ("DATA-002",)),),
            build_leaky_training,
        ),
        Scenario(
            "test-set-tampered",
            "Test labels edited",
            (Step("2.1.0", OUTSIDE, ("DATA-001",)),),
            build_test_set_tampered,
        ),
        Scenario(
            "new-architecture",
            "Modification not listed in the plan",
            (Step("2.1.0", OUTSIDE, ("PLAN-002",)),),
            build_new_architecture,
        ),
        Scenario(
            "out-of-scope-data",
            "Paediatric rows in training",
            (Step("2.1.0", OUTSIDE, ("DATA-003",)),),
            build_out_of_scope_data,
        ),
        Scenario(
            "bio-creep",
            "Five updates each -0.008 AUROC: each passes vs previous, "
            "the fifth breaks the anchor budget",
            (
                *(Step(f"2.{k}.0", ACCEPTED, ()) for k in range(1, BIO_CREEP_STEPS)),
                Step(f"2.{BIO_CREEP_STEPS}.0", FAILED, ("LIFE-001",)),
            ),
            build_bio_creep,
        ),
        Scenario(
            "underpowered",
            "Test set too small for the margin",
            (Step("2.1.0", ACCEPTED, (), ("PERF-006",)),),
            build_underpowered,
        ),
    )
}


def run_scenario(
    name: str,
    out: Path,
    *,
    cohort: Cohort | None = None,
    n_replicates: int = 2000,
    seed: int = 0,
    on_step: Callable[[Path, Evaluation, dict[str, Any] | None], None] | None = None,
) -> ScenarioResult:
    """Build one scenario under ``out / name``, evaluate every step and record it in a ledger.

    Args:
        name: Scenario name.
        out: Parent directory.
        cohort: Shared cohort, built if not given.
        n_replicates: Bootstrap replicates.
        seed: Resampling seed.
        on_step: Called after each step with its directory, evaluation and ledger entry,
            for example to write reports.
    """
    scenario = SCENARIOS[name]
    root = out / name
    cohort = cohort or make_cohort()
    ledger = root / "ledger.jsonl"
    result = ScenarioResult(scenario, root)
    for step, built in zip(scenario.steps, scenario.build(cohort, root), strict=True):
        with exclusive(ledger):
            evaluation = evaluate(
                **built["inputs"],
                history=load_history(ledger),
                now=built["now"],
                n_replicates=n_replicates,
                seed=seed,
            )
            entry = append(ledger, evaluation, already_locked=True)
        if on_step is not None:
            on_step(built["directory"], evaluation, entry)
        result.steps.append(StepResult(step, evaluation))
    return result


def run_all(
    out: Path,
    *,
    names: list[str] | None = None,
    n_replicates: int = 2000,
    seed: int = 0,
    on_step: Callable[[Path, Evaluation, dict[str, Any] | None], None] | None = None,
) -> list[ScenarioResult]:
    """Run every scenario (or ``names``) and return their results."""
    cohort = make_cohort()
    return [
        run_scenario(
            name, out, cohort=cohort, n_replicates=n_replicates, seed=seed, on_step=on_step
        )
        for name in (names or list(SCENARIOS))
    ]

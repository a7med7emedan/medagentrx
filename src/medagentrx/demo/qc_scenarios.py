# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Planted deployment QC scenarios on the synthetic cohort.

The control records come from the cohort's development sample, so they are
disjoint from the locked test set and the training manifest by construction.
The live stack is the released version's calibrated model plus a little
numerical noise, as a GPU or a threaded runtime gives. Each scenario first
completes the baseline, then plants one change, and every run must give
exactly its expected verdict.
"""

from __future__ import annotations

import datetime as dt
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import yaml

from medagentrx.checks.live_checks import sd_floor
from medagentrx.demo.cohort import Cohort, Recipe, logistic_recalibration, make_cohort
from medagentrx.demo.plan import demo_plan
from medagentrx.demo.scenarios import (
    INTENDED_USE_SHA256,
    INTENDED_USE_TEXT,
    improved_version,
    locked_fingerprint,
    previous_version,
    write_parquet,
)
from medagentrx.errors import InputError
from medagentrx.io.fingerprint import id_fingerprint
from medagentrx.io.hashing import sha256_file
from medagentrx.ledger import append_qc, read_entries
from medagentrx.qc import QcRun, run_qc

FloatArray = npt.NDArray[np.float64]

QC_RECORDS = 200
QC_NOISE = 1.0e-7
"""Per-record numerical noise of the live stack."""
QC_TOLERANCE = 1.0e-6
QC_BASELINE = 10
QC_START = dt.datetime(2026, 6, 1, 6, 0, tzinfo=dt.UTC)
ERROR = "ERROR"
RAW_COLUMNS = ("row_id", "patient_id", "sex", "age", "site", "lactate")
FLOOR = sd_floor(QC_TOLERANCE, QC_RECORDS)


@dataclass(frozen=True)
class QcStep:
    """One QC run in a scenario and what it must give."""

    expected: str
    expected_failed: tuple[str, ...] = ()
    expected_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class QcScenario:
    """A planted change to the live system and the outcome it must produce."""

    name: str
    planted: str
    steps: tuple[QcStep, ...]
    build: Callable[[Cohort, Path], list[dict[str, Any]]]


@dataclass
class QcStepResult:
    """What one QC run actually gave."""

    step: QcStep
    verdict: str
    failed: tuple[str, ...]
    warnings: tuple[str, ...]
    run: QcRun | None = None

    @property
    def ok(self) -> bool:
        """True when verdict, failed checks and warnings are exactly as expected."""
        return (
            self.verdict == self.step.expected
            and self.failed == self.step.expected_failed
            and self.warnings == self.step.expected_warnings
        )


@dataclass
class QcScenarioResult:
    """All runs of one QC scenario."""

    scenario: QcScenario
    directory: Path
    steps: list[QcStepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every run matched."""
        return len(self.steps) == len(self.scenario.steps) and all(s.ok for s in self.steps)


def _expit(x: FloatArray) -> FloatArray:
    result: FloatArray = 1.0 / (1.0 + np.exp(-x))
    return result


def _expected(cohort: Cohort, version: Recipe) -> FloatArray:
    """The version's calibrated scores on the control records, as its released stack gives."""
    dev = cohort.development
    if dev is None:  # pragma: no cover  # make_cohort always draws one
        raise ValueError("the cohort has no development sample")
    intercept, slope = logistic_recalibration(dev.y, version(dev))
    return _expit(intercept + slope * version(dev)[:QC_RECORDS])


@dataclass(frozen=True)
class ControlSet:
    """Files of a synthetic control set: plan, raw inputs, ids and expected scores."""

    plan: Path
    control: Path
    ids: list[str]
    expected: dict[str, tuple[Path, FloatArray]]


def prepare_control_set(
    cohort: Cohort, root: Path, *, versions: tuple[str, ...] = ("2.0.0",)
) -> ControlSet:
    """Write raw control inputs, expected scores and a demo plan with a QC block."""
    root.mkdir(parents=True, exist_ok=True)
    dev = cohort.development
    if dev is None:  # pragma: no cover
        raise ValueError("the cohort has no development sample")
    raw = {name: list(dev.test[name][:QC_RECORDS]) for name in RAW_COLUMNS}
    control = write_parquet(root / "control_inputs.parquet", raw)
    ids = [str(i) for i in raw["row_id"]]
    recipes = {"2.0.0": previous_version(cohort), "2.1.0": improved_version(cohort)}
    expected: dict[str, tuple[Path, FloatArray]] = {}
    for version in versions:
        scores = _expected(cohort, recipes[version])
        path = write_parquet(
            root / f"expected-{version}.parquet", {"row_id": list(ids), "y_score": scores.tolist()}
        )
        expected[version] = (path, scores)
    plan = demo_plan(
        test_set_sha256=locked_fingerprint(cohort), intended_use_sha256=INTENDED_USE_SHA256
    )
    plan["deployment_qc"] = {
        "control_inputs_sha256": sha256_file(control),
        "control_ids_fingerprint": id_fingerprint(ids),
        "expected_scores": {v: sha256_file(p) for v, (p, _) in expected.items()},
        "tolerance": {"absolute": QC_TOLERANCE},
        "rules": ["1_2s", "1_3s", "2_2s", "R_4s", "10_x"],
        "baseline_runs": QC_BASELINE,
        "schedule": "daily",
    }
    plan_path = root / "change-plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    (root / "intended-use.txt").write_bytes(INTENDED_USE_TEXT)
    return ControlSet(plan_path, control, ids, expected)


def _run(
    setup: ControlSet,
    root: Path,
    k: int,
    scores: FloatArray | None = None,
    *,
    version: str = "2.0.0",
    ids: list[str] | None = None,
    raw: dict[str, list[object]] | None = None,
) -> dict[str, Any]:
    """Inputs of the k-th run; ``raw`` overrides the score file columns."""
    columns: dict[str, list[object]] = raw or {
        "row_id": list(ids or setup.ids),
        "y_score": np.clip(scores, 0.0, 1.0).tolist() if scores is not None else [],
    }
    live = write_parquet(root / "runs" / f"live-{k:03d}.parquet", columns)
    return {
        "scores": live,
        "expected": setup.expected[version][0],
        "model_version": version,
        "control_inputs": setup.control,
        "now": QC_START + dt.timedelta(days=k),
        "plan": setup.plan,
    }


def _baseline(
    setup: ControlSet, root: Path, rng: np.random.Generator
) -> tuple[list[dict[str, Any]], FloatArray]:
    expected = setup.expected["2.0.0"][1]
    runs = [
        _run(setup, root, k, expected + rng.normal(0.0, QC_NOISE, QC_RECORDS))
        for k in range(QC_BASELINE)
    ]
    return runs, expected


def build_clean(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Ten baseline runs and ten monitored runs with numerical noise only."""
    setup = prepare_control_set(cohort, root)
    rng = np.random.default_rng(11)
    runs, expected = _baseline(setup, root, rng)
    runs += [
        _run(setup, root, QC_BASELINE + k, expected + rng.normal(0.0, QC_NOISE, QC_RECORDS))
        for k in range(10)
    ]
    return runs


def build_dependency_change(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """A library upgrade moves every score by 3e-7, inside the per-record tolerance."""
    setup = prepare_control_set(cohort, root)
    rng = np.random.default_rng(12)
    runs, expected = _baseline(setup, root, rng)
    shifted = expected + 3.0e-7 + rng.normal(0.0, QC_NOISE, QC_RECORDS)
    return [*runs, _run(setup, root, QC_BASELINE, shifted)]


def build_preprocessing_change(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """A changed preprocessing step moves 20 of the 200 control records by 2e-5."""
    setup = prepare_control_set(cohort, root)
    rng = np.random.default_rng(13)
    runs, expected = _baseline(setup, root, rng)
    shift = np.zeros(QC_RECORDS)
    shift[::10] = 2.0e-5
    changed = expected + shift + rng.normal(0.0, QC_NOISE, QC_RECORDS)
    return [*runs, _run(setup, root, QC_BASELINE, changed)]


def build_outlier_run(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """One run lands 2.5 SD from the mean: a 1_2s warning, not a rejection."""
    setup = prepare_control_set(cohort, root)
    rng = np.random.default_rng(14)
    runs, expected = _baseline(setup, root, rng)
    outlier = expected + 2.5 * FLOOR + rng.normal(0.0, QC_NOISE, QC_RECORDS)
    return [*runs, _run(setup, root, QC_BASELINE, outlier)]


def build_slow_drift(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Scores creep upwards by a fraction of an SD per run; 10_x catches it."""
    setup = prepare_control_set(cohort, root)
    rng = np.random.default_rng(15)
    runs, expected = _baseline(setup, root, rng)
    for k in range(10):
        drift = (0.6 + 0.08 * k) * FLOOR
        runs.append(
            _run(
                setup,
                root,
                QC_BASELINE + k,
                expected + drift + rng.normal(0.0, QC_NOISE, QC_RECORDS),
            )
        )
    return runs


def build_unreleased_version(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """Version 2.1.0 runs live, but only 2.0.0 has been released."""
    setup = prepare_control_set(cohort, root, versions=("2.0.0", "2.1.0"))
    rng = np.random.default_rng(16)
    scores = setup.expected["2.1.0"][1] + rng.normal(0.0, QC_NOISE, QC_RECORDS)
    return [_run(setup, root, 0, scores, version="2.1.0")]


def build_wrong_ids(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """The score file covers other records than the locked control set."""
    setup = prepare_control_set(cohort, root)
    rng = np.random.default_rng(17)
    ids = [*setup.ids[:-5], *(f"OTHER-{i}" for i in range(5))]
    scores = setup.expected["2.0.0"][1] + rng.normal(0.0, QC_NOISE, QC_RECORDS)
    return [_run(setup, root, 0, scores, ids=ids)]


def build_malformed(cohort: Cohort, root: Path) -> list[dict[str, Any]]:
    """A score file with a value that is not a number: an input error, exit 3."""
    setup = prepare_control_set(cohort, root)
    raw: dict[str, list[object]] = {
        "row_id": list(setup.ids),
        "y_score": ["not a number", *(["0.5"] * (QC_RECORDS - 1))],
    }
    return [_run(setup, root, 0, raw=raw)]


IN_CONTROL, OUTSIDE = "IN_CONTROL", "OUTSIDE_PLAN"
_BASE_STEPS = (QcStep(IN_CONTROL),) * QC_BASELINE

QC_SCENARIOS: dict[str, QcScenario] = {
    s.name: s
    for s in (
        QcScenario(
            "qc-clean",
            "Numerical noise only, inside tolerance",
            _BASE_STEPS + (QcStep(IN_CONTROL),) * 10,
            build_clean,
        ),
        QcScenario(
            "qc-dependency-change",
            "Library upgrade shifts every score by 3e-7",
            (*_BASE_STEPS, QcStep(OUTSIDE, ("LIVE-004",))),
            build_dependency_change,
        ),
        QcScenario(
            "qc-preprocessing-change",
            "Preprocessing change moves 20 of 200 records",
            (*_BASE_STEPS, QcStep(OUTSIDE, ("LIVE-003", "LIVE-004"))),
            build_preprocessing_change,
        ),
        QcScenario(
            "qc-outlier-run",
            "One run 2.5 SD from the mean",
            (*_BASE_STEPS, QcStep(IN_CONTROL, (), ("LIVE-004",))),
            build_outlier_run,
        ),
        QcScenario(
            "qc-slow-drift",
            "Scores creep upwards run after run",
            _BASE_STEPS + (QcStep(IN_CONTROL),) * 9 + (QcStep(OUTSIDE, ("LIVE-004",)),),
            build_slow_drift,
        ),
        QcScenario(
            "qc-unreleased-version",
            "Version 2.1.0 runs live before its release",
            (QcStep(OUTSIDE, ("LIVE-001",)),),
            build_unreleased_version,
        ),
        QcScenario(
            "qc-wrong-ids",
            "Score file for other records",
            (QcStep(OUTSIDE, ("LIVE-002",)),),
            build_wrong_ids,
        ),
        QcScenario(
            "qc-malformed",
            "Score file with a value that is not a number",
            (QcStep(ERROR),),
            build_malformed,
        ),
    )
}


def run_qc_scenario(
    name: str,
    out: Path,
    *,
    cohort: Cohort | None = None,
    on_step: Callable[[Path, QcRun, dict[str, Any]], None] | None = None,
) -> QcScenarioResult:
    """Build one QC scenario under ``out / name``, run every QC run and record it."""
    scenario = QC_SCENARIOS[name]
    root = out / name
    if root.exists():
        shutil.rmtree(root)
    cohort = cohort or make_cohort()
    ledger = root / "ledger.jsonl"
    result = QcScenarioResult(scenario, root)
    for step, inputs in zip(scenario.steps, scenario.build(cohort, root), strict=True):
        try:
            run = run_qc(
                plan=inputs["plan"],
                scores=inputs["scores"],
                expected=inputs["expected"],
                model_version=inputs["model_version"],
                control_inputs=inputs["control_inputs"],
                entries=read_entries(ledger),
                now=inputs["now"],
            )
        except InputError:
            result.steps.append(QcStepResult(step, ERROR, (), ()))
            continue
        entry = append_qc(ledger, run)
        if on_step is not None:
            on_step(root, run, entry)
        warnings = tuple(f.check_id for f in run.findings if f.status.value == "warn")
        result.steps.append(
            QcStepResult(step, run.verdict.value, tuple(run.failed_checks), warnings, run)
        )
    return result


def run_all_qc(
    out: Path,
    *,
    names: list[str] | None = None,
    on_step: Callable[[Path, QcRun, dict[str, Any]], None] | None = None,
) -> list[QcScenarioResult]:
    """Run every QC scenario (or ``names``) and return their results."""
    cohort = make_cohort()
    return [
        run_qc_scenario(name, out, cohort=cohort, on_step=on_step)
        for name in (names or list(QC_SCENARIOS))
    ]


__all__ = [
    "FLOOR",
    "QC_NOISE",
    "QC_SCENARIOS",
    "ControlSet",
    "QcScenarioResult",
    "prepare_control_set",
    "run_all_qc",
    "run_qc_scenario",
]

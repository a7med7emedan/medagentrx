# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Every planted scenario must give exactly its expected verdict and failing checks."""

from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from medagentrx import load_plan
from medagentrx.cli import app
from medagentrx.demo import SCENARIOS, ScenarioResult, run_all
from medagentrx.demo.cohort import make_cohort, sigma_for_auc
from medagentrx.demo.plan import demo_plan
from medagentrx.demo.scenarios import INTENDED_USE_SHA256, locked_fingerprint
from medagentrx.io.fingerprint import fingerprint_file
from medagentrx.io.predictions import load_predictions
from medagentrx.ledger import load_history, verify
from medagentrx.plan.models import ChangePlan
from tests.conftest import EXAMPLE_DIR, EXAMPLE_PLAN


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ScenarioResult]:
    out = tmp_path_factory.mktemp("demo")
    return {r.scenario.name: r for r in run_all(out)}


def test_brief_scenarios_are_present() -> None:
    assert list(SCENARIOS) == [
        "good-update",
        "subgroup-harm",
        "miscalibrated",
        "leaky-training",
        "test-set-tampered",
        "new-architecture",
        "out-of-scope-data",
        "bio-creep",
        "underpowered",
    ]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_gives_its_exact_verdict(results: dict[str, ScenarioResult], name: str) -> None:
    result = results[name]
    for step in result.steps:
        evaluation = step.evaluation
        warnings = [f.check_id for f in evaluation.findings if f.status.value == "warn"]
        assert evaluation.verdict is step.step.expected, (name, evaluation.failed_checks)
        assert tuple(evaluation.failed_checks) == step.step.expected_failed
        assert tuple(warnings) == step.step.expected_warnings
    assert result.ok
    assert verify(result.directory / "ledger.jsonl").ok


def test_bio_creep_story(results: dict[str, ScenarioResult]) -> None:
    steps = results["bio-creep"].steps
    deltas = [s.evaluation.finding("LIFE-001").details["test"]["delta"] for s in steps]
    assert deltas == pytest.approx([-0.008, -0.016, -0.024, -0.032, -0.040], abs=1e-4)
    vs_previous = [s.evaluation.finding("PERF-001").details["tests"]["vs_previous"] for s in steps]
    assert all(t["non_inferior"] for t in vs_previous)
    assert steps[-1].evaluation.finding("LIFE-001").details["test"]["ci_lower"] < -0.04
    history = load_history(results["bio-creep"].directory / "ledger.jsonl")
    assert history.looks_used == 5
    assert len(history.releases) == 4


def test_planted_properties(results: dict[str, ScenarioResult]) -> None:
    mis = results["miscalibrated"].steps[0].evaluation
    assert mis.finding("PERF-003").details["candidate"]["slope"] == pytest.approx(0.6, abs=0.01)
    assert mis.finding("PERF-001").details["tests"]["vs_previous"]["delta"] == pytest.approx(
        0, abs=1e-5
    )
    harm = results["subgroup-harm"].steps[0].evaluation
    groups = harm.finding("PERF-005").details["subgroups"]
    site_c = next(g for g in groups if g["column"] == "site" and g["level"] == "C")
    assert site_c["delta"] == pytest.approx(-0.06, abs=1e-3)
    assert harm.finding("PERF-001").details["tests"]["vs_previous"]["delta"] > 0
    leak = results["leaky-training"].steps[0].evaluation
    assert leak.finding("DATA-002").details["overlaps"]["patient_id"]["count"] == 300
    scope = results["out-of-scope-data"].steps[0].evaluation
    assert scope.finding("DATA-003").details["failing"] == 150
    power = results["underpowered"].steps[0].evaluation.finding("PERF-006").details["power"]
    assert power < 0.8


def test_cohort_is_deterministic() -> None:
    a, b = make_cohort(n_test=500, n_train=500), make_cohort(n_test=500, n_train=500)
    assert np.array_equal(a.truth, b.truth)
    assert a.test == b.test
    assert a.train == b.train
    assert 0.08 < make_cohort().y.mean() < 0.16


def test_sigma_target_above_ceiling() -> None:
    cohort = make_cohort(n_test=500, n_train=10)
    with pytest.raises(ValueError, match="above the noiseless value"):
        sigma_for_auc(cohort, 0.999)


def test_example_matches_the_demo() -> None:
    cohort = make_cohort()
    expected = ChangePlan.model_validate(
        demo_plan(
            test_set_sha256=locked_fingerprint(cohort), intended_use_sha256=INTENDED_USE_SHA256
        )
    )
    assert load_plan(EXAMPLE_PLAN) == expected
    assert fingerprint_file(EXAMPLE_DIR / "candidate.parquet") == locked_fingerprint(cohort)
    shipped = load_predictions(EXAMPLE_DIR / "candidate.parquet")
    assert shipped.n == 20_000
    meta = yaml.safe_load((EXAMPLE_DIR / "model.yaml").read_text(encoding="utf-8"))
    import hashlib

    manifest = (EXAMPLE_DIR / "train_manifest.parquet").read_bytes()
    assert meta["training_manifest_sha256"] == hashlib.sha256(manifest).hexdigest()


def test_demo_command(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--out", str(tmp_path), "--scenario", "new-architecture"])
    assert result.exit_code == 0, result.output
    assert "Synthetic data only" in result.output
    assert "1 of 1 scenarios gave their expected verdict" in result.output
    assert (tmp_path / "new-architecture" / "report" / "report.json").exists()
    bad = runner.invoke(app, ["demo", "--out", str(tmp_path), "--scenario", "nope"])
    assert bad.exit_code == 3


def test_demo_command_reports_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from medagentrx.demo import scenarios
    from medagentrx.engine import Verdict

    original = scenarios.SCENARIOS["new-architecture"]
    broken = scenarios.Scenario(
        original.name,
        original.planted,
        (scenarios.Step("2.1.0", Verdict.ACCEPTED, ()),),
        original.build,
    )
    monkeypatch.setitem(scenarios.SCENARIOS, "new-architecture", broken)
    result = CliRunner().invoke(
        app, ["demo", "--out", str(tmp_path), "--scenario", "new-architecture"]
    )
    assert result.exit_code == 1
    assert " NO" in result.output

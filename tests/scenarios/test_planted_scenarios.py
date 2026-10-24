# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Every planted scenario must give exactly its expected verdict and failing checks."""

import json
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
from medagentrx.engine import Evaluation
from medagentrx.io.fingerprint import fingerprint_file, id_fingerprint
from medagentrx.io.hashing import sha256_file
from medagentrx.io.predictions import load_predictions, load_row_ids
from medagentrx.ledger import load_history, verify
from medagentrx.plan.models import ChangePlan
from tests.conftest import EXAMPLE_DIR, EXAMPLE_PLAN


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ScenarioResult]:
    out = tmp_path_factory.mktemp("demo")
    return {r.scenario.name: r for r in run_all(out)}


def _evaluation(result: ScenarioResult, index: int = 0) -> Evaluation:
    evaluation = result.steps[index].evaluation
    assert evaluation is not None
    return evaluation


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
        "peeking-agent",
    ]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_gives_its_exact_verdict(results: dict[str, ScenarioResult], name: str) -> None:
    result = results[name]
    assert len(result.steps) == len(result.scenario.steps)
    for step in result.steps:
        assert step.verdict is step.step.expected, (name, step.failed)
        assert step.failed == step.step.expected_failed
        assert step.warnings == step.step.expected_warnings
    assert result.ok
    assert verify(result.directory / "ledger.jsonl").ok


def test_peeking_agent_story(results: dict[str, ScenarioResult]) -> None:
    result = results["peeking-agent"]
    answers = json.loads((result.directory / "agent-answers.json").read_text(encoding="utf-8"))
    assert [a["looks_used"] for a in answers] == [*range(1, 21), 20, 20, 20, 20, 20]
    assert all(not a["allowed"] for a in answers[20:])
    assert all("AUROC" not in a["reason"] and "0." not in a["reason"] for a in answers)
    history = load_history(result.directory / "ledger.jsonl")
    assert history.looks_used == 20
    assert history.releases == ()
    assert history.alpha is not None
    assert history.alpha.spent == 0.0


def test_bio_creep_story(results: dict[str, ScenarioResult]) -> None:
    steps = results["bio-creep"].steps
    evaluations = [_evaluation(results["bio-creep"], i) for i in range(len(steps))]
    deltas = [e.finding("LIFE-001").details["test"]["delta"] for e in evaluations]
    assert deltas == pytest.approx([-0.008, -0.016, -0.024, -0.032, -0.040], abs=1e-4)
    vs_previous = [e.finding("PERF-001").details["tests"]["vs_previous"] for e in evaluations]
    assert all(t["non_inferior"] for t in vs_previous)
    assert evaluations[-1].finding("LIFE-001").details["test"]["ci_lower"] < -0.04
    history = load_history(results["bio-creep"].directory / "ledger.jsonl")
    assert history.looks_used == 5
    assert len(history.releases) == 4


def test_planted_properties(results: dict[str, ScenarioResult]) -> None:
    mis = _evaluation(results["miscalibrated"])
    calibration = mis.finding("PERF-003").details
    # Recalibrated on development data, version 2.0.0 is close to calibrated on the test set;
    # the planted defect shrinks its slope by 0.6.
    assert 0.9 < calibration["previous"]["slope"] < 1.2
    ratio = calibration["candidate"]["slope"] / calibration["previous"]["slope"]
    assert ratio == pytest.approx(0.6, abs=0.01)
    good = _evaluation(results["good-update"]).finding("PERF-003")
    assert good.status.value == "pass"
    assert good.details["candidate"]["slope"] != pytest.approx(1.0, abs=1e-3)
    assert mis.finding("PERF-001").details["tests"]["vs_previous"]["delta"] == pytest.approx(
        0, abs=1e-5
    )
    harm = _evaluation(results["subgroup-harm"])
    groups = harm.finding("PERF-005").details["subgroups"]
    site_c = next(g for g in groups if g["column"] == "site" and g["level"] == "C")
    assert site_c["delta"] == pytest.approx(-0.06, abs=1e-3)
    assert harm.finding("PERF-001").details["tests"]["vs_previous"]["delta"] > 0
    leak = _evaluation(results["leaky-training"])
    assert leak.finding("DATA-002").details["overlaps"]["patient_id"]["count"] == 300
    scope = _evaluation(results["out-of-scope-data"])
    assert scope.finding("DATA-003").details["failing"] == 150
    power = _evaluation(results["underpowered"]).finding("PERF-006").details["power"]
    assert power < 0.8


def test_development_sample_is_separate_from_the_test_set() -> None:
    small = make_cohort(n_test=300, n_train=10, n_development=200)
    larger = make_cohort(n_test=300, n_train=10, n_development=400)
    assert small.development is not None
    assert small.development.n == 200
    assert small.y.tolist() == larger.y.tolist()
    assert not set(small.development.test["patient_id"]) & set(small.test["patient_id"])
    assert small.development.development is None


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
    example = load_plan(EXAMPLE_PLAN)
    assert example.model_copy(update={"deployment_qc": None}) == expected
    qc = example.deployment_qc
    assert qc is not None
    folder = EXAMPLE_DIR / "qc"
    assert qc.control_inputs_sha256 == sha256_file(folder / "control_inputs.parquet")
    assert qc.expected_scores == {"2.0.0": sha256_file(folder / "expected-2.0.0.parquet")}
    ids = load_row_ids(folder / "control_inputs.parquet")
    assert qc.control_ids_fingerprint == id_fingerprint(ids)
    assert not set(ids) & set(load_row_ids(EXAMPLE_DIR / "candidate.parquet"))
    assert not set(ids) & set(load_row_ids(EXAMPLE_DIR / "train_manifest.parquet"))
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
    for name in ("report.json", "report.html", "summary.md", "junit.xml"):
        assert (tmp_path / "new-architecture" / "report" / name).exists()
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

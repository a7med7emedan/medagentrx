# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import datetime as dt
import json
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from medagentrx import QcVerdict, qc
from medagentrx.checks.live_checks import sd_floor
from medagentrx.cli import app
from medagentrx.demo.cohort import make_cohort
from medagentrx.demo.plan import demo_plan
from medagentrx.demo.qc_scenarios import QC_NOISE, ControlSet, prepare_control_set
from medagentrx.demo.scenarios import INTENDED_USE_SHA256, locked_fingerprint, write_parquet
from medagentrx.errors import InputError
from medagentrx.guard import Guard
from medagentrx.io.fingerprint import id_fingerprint
from medagentrx.io.hashing import sha256_file
from medagentrx.io.predictions import load_row_ids, load_scores
from medagentrx.ledger import (
    LedgerError,
    append_qc,
    build_qc_entry,
    entry_hash,
    head_path_for,
    read_entries,
    summarize,
    verify,
)
from medagentrx.plan import load_plan, plan_fingerprint
from medagentrx.plan.models import ChangePlan
from medagentrx.qc import (
    qc_block_yaml,
    qc_entry_yaml,
    qc_history,
    qc_init,
    released_version,
    run_qc,
)
from medagentrx.render_plan import build_document
from medagentrx.report.qc_report import qc_figures, qc_report_dict, render_qc_markdown
from medagentrx.signing import generate_key_pair
from tests.conftest import REPO_ROOT

runner = CliRunner()
T0 = dt.datetime(2026, 6, 1, 6, tzinfo=dt.UTC)
EXAMPLE = REPO_ROOT / "examples" / "sepsis-risk"
V0_1_EXAMPLE_FINGERPRINT = "ae130793a1c99b54b33743503fdd52124fccab5c0a5db8d818b3d426f8f3b29a"


@pytest.fixture(scope="module")
def cohort() -> Any:
    return make_cohort(n_test=1500, n_train=300, n_development=300)


@pytest.fixture
def control(cohort: Any, tmp_path: Path) -> ControlSet:
    return prepare_control_set(cohort, tmp_path / "qc", versions=("2.0.0", "2.1.0"))


def _edit_plan(control: ControlSet, **changes: Any) -> Path:
    data = yaml.safe_load(control.plan.read_text(encoding="utf-8"))
    data["deployment_qc"].update(changes)
    control.plan.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return control.plan


def _scores(control: ControlSet, name: str, values: Any, ids: list[str] | None = None) -> Path:
    path = control.plan.parent / f"{name}.parquet"
    write_parquet(
        path, {"row_id": list(ids or control.ids), "y_score": np.clip(values, 0, 1).tolist()}
    )
    return path


def _noise(control: ControlSet, seed: int, shift: float = 0.0, version: str = "2.0.0") -> Any:
    expected = control.expected[version][1]
    return expected + shift + np.random.default_rng(seed).normal(0.0, QC_NOISE, len(expected))


def _run(
    control: ControlSet,
    live: Path,
    *,
    ledger: Path | None = None,
    version: str = "2.0.0",
    k: int = 0,
    record: bool = True,
    **kwargs: Any,
) -> Any:
    ledger = ledger or control.plan.parent / "ledger.jsonl"
    run = run_qc(
        plan=control.plan,
        scores=live,
        expected=control.expected[version][0],
        model_version=version,
        entries=read_entries(ledger),
        now=T0 + dt.timedelta(days=k),
        **kwargs,
    )
    if record:
        append_qc(ledger, run)
    return run


# Plan schema --------------------------------------------------------------------------


def test_existing_plans_keep_their_fingerprint() -> None:
    plan = ChangePlan.model_validate(
        demo_plan(test_set_sha256=_example_locked(), intended_use_sha256=INTENDED_USE_SHA256)
    )
    assert plan.deployment_qc is None
    assert plan_fingerprint(plan) == V0_1_EXAMPLE_FINGERPRINT
    example = load_plan(EXAMPLE / "change-plan.yaml")
    assert plan_fingerprint(example.model_copy(update={"deployment_qc": None})) == (
        V0_1_EXAMPLE_FINGERPRINT
    )


def _example_locked() -> str:
    return load_plan(EXAMPLE / "change-plan.yaml").data_management.locked_test_set.sha256


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rules": ["1_2s", "1_2s"]}, "rules must not repeat"),
        ({"rules": ["4_1s"]}, "rules"),
        ({"rules": []}, "rules"),
        ({"sd": 0.0}, "sd"),
        ({"baseline_runs": 4}, "baseline_runs"),
        ({"expected_scores": {}}, "expected_scores"),
        ({"control_ids_fingerprint": "abc"}, "control_ids_fingerprint"),
        ({"tolerance": {"absolute": 0.0}}, "absolute"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_qc_block_is_strict(control: ControlSet, change: dict[str, Any], message: str) -> None:
    data = yaml.safe_load(control.plan.read_text(encoding="utf-8"))
    data["deployment_qc"].update(change)
    with pytest.raises(ValidationError, match=message):
        ChangePlan.model_validate(data)


# Inputs ----------------------------------------------------------------------------------


def test_score_loaders(control: ControlSet, tmp_path: Path) -> None:
    scores = load_scores(control.expected["2.0.0"][0])
    assert scores.n == len(control.ids)
    assert list(scores.by_id())[:3] == control.ids[:3]
    assert id_fingerprint(control.ids) == id_fingerprint(list(reversed(control.ids)))
    assert id_fingerprint(control.ids) != id_fingerprint(control.ids[1:])
    (tmp_path / "empty.csv").write_text("row_id,y_score\n", encoding="utf-8")
    with pytest.raises(InputError, match="no data rows"):
        load_scores(tmp_path / "empty.csv")
    with pytest.raises(InputError, match="no data rows"):
        load_row_ids(tmp_path / "empty.csv")
    (tmp_path / "high.csv").write_text("row_id,y_score\na,1.5\n", encoding="utf-8")
    with pytest.raises(InputError, match="outside"):
        load_scores(tmp_path / "high.csv")


# qc init ---------------------------------------------------------------------------------


def test_qc_init_block_validates(control: ControlSet, cohort: Any, tmp_path: Path) -> None:
    init = qc_init(
        control_inputs=control.control,
        scores=control.expected["2.0.0"][0],
        version="2.0.0",
    )
    assert init.records == len(control.ids)
    assert init.checked_against == ()
    block = qc_block_yaml(init, tolerance=2.5e-6)
    plan = demo_plan(
        test_set_sha256=locked_fingerprint(cohort), intended_use_sha256=INTENDED_USE_SHA256
    )
    plan_text = yaml.safe_dump(plan, sort_keys=False) + block
    (tmp_path / "p.yaml").write_text(plan_text, encoding="utf-8")
    qc_block = load_plan(tmp_path / "p.yaml").deployment_qc
    assert qc_block is not None
    assert qc_block.tolerance.absolute == 2.5e-6
    assert qc_block.expected_scores == {"2.0.0": init.expected_sha256}
    assert qc_block.sd is None
    later = qc_init(
        control_inputs=control.control,
        scores=control.expected["2.1.0"][0],
        version="2.1.0",
        plan=control.plan,
    )
    assert qc_entry_yaml(later) == f'    "2.1.0": "{later.expected_sha256}"\n'


def test_qc_init_refusals(control: ControlSet, tmp_path: Path) -> None:
    base: dict[str, Any] = {"control_inputs": control.control, "version": "2.0.0"}
    partial = _scores(control, "partial", control.expected["2.0.0"][1][:-1], control.ids[:-1])
    with pytest.raises(InputError, match="does not cover exactly the control ids"):
        qc_init(scores=partial, **base)
    overlap = tmp_path / "test.csv"
    overlap.write_text(
        f"row_id,y_true,y_score\n{control.ids[0]},1,0.5\nZ,0,0.1\n", encoding="utf-8"
    )
    with pytest.raises(InputError, match="1 control ids also appear in the locked test set"):
        qc_init(scores=control.expected["2.0.0"][0], test_set=overlap, **base)
    manifest = tmp_path / "train.csv"
    manifest.write_text(f"row_id,patient_id\n{control.ids[1]},P\n", encoding="utf-8")
    with pytest.raises(InputError, match="training manifest"):
        qc_init(scores=control.expected["2.0.0"][0], manifest=manifest, **base)
    other = tmp_path / "other_inputs.csv"
    other.write_text("row_id,age\n" + "".join(f"{i},50\n" for i in control.ids), encoding="utf-8")
    with pytest.raises(InputError, match="differs from the one the plan locks"):
        qc_init(
            control_inputs=other,
            scores=control.expected["2.0.0"][0],
            version="2.0.0",
            plan=control.plan,
        )


def test_qc_init_checks_the_example_sets() -> None:
    init = qc_init(
        control_inputs=EXAMPLE / "qc" / "control_inputs.parquet",
        scores=EXAMPLE / "qc" / "expected-2.0.0.parquet",
        version="2.0.0",
        test_set=EXAMPLE / "candidate.parquet",
        manifest=EXAMPLE / "train_manifest.parquet",
    )
    assert init.checked_against == ("locked test set", "training manifest")


# The LIVE checks -------------------------------------------------------------------------


def test_clean_run_during_baseline(control: ControlSet) -> None:
    run = _run(control, _scores(control, "live", _noise(control, 1)))
    assert run.verdict is QcVerdict.IN_CONTROL
    assert run.exit_code == 0
    assert run.finding("LIVE-004").status.value == "not_applicable"
    assert run.notes
    assert "Baseline run 1 of" in run.notes[0]
    assert run.z is None
    assert run.mean is None
    assert run.bias is not None
    assert abs(run.bias) < 1e-7


def test_released_version_and_history() -> None:
    plan = type("P", (), {"anchor_version": "2.0.0"})()
    assert released_version(plan, []) == "2.0.0"
    entries = [
        {"kind": "release", "candidate_version": "2.1.0"},
        {"kind": "evaluation", "candidate_version": "2.2.0"},
        {"kind": "release", "candidate_version": "2.2.0"},
    ]
    assert released_version(plan, entries) == "2.2.0"
    qc_entries = [
        {
            "kind": "qc",
            "model_version": "2.0.0",
            "seq": 0,
            "recorded_at": T0.isoformat(),
            "verdict": "IN_CONTROL",
            "qc": {"bias": 1e-9},
        },
        {
            "kind": "qc",
            "model_version": "2.0.0",
            "seq": 1,
            "recorded_at": T0.isoformat(),
            "verdict": "OUTSIDE_PLAN",
            "qc": {"bias": None},
        },
        {
            "kind": "qc",
            "model_version": "2.1.0",
            "seq": 2,
            "recorded_at": T0.isoformat(),
            "verdict": "IN_CONTROL",
            "qc": {"bias": 2e-9},
        },
    ]
    history = qc_history(qc_entries, "2.0.0")
    assert [(h.seq, h.bias, h.in_control) for h in history] == [(0, 1e-9, True)]


def test_unreleased_version(control: ControlSet) -> None:
    run = _run(
        control, _scores(control, "live", _noise(control, 2, version="2.1.0")), version="2.1.0"
    )
    assert run.verdict is QcVerdict.OUTSIDE_PLAN
    assert run.exit_code == 2
    assert run.failed_checks == ["LIVE-001"]
    assert run.finding("LIVE-003").status.value == "skipped"
    assert run.bias is None
    assert run.max_abs_deviation is None


def test_binding_problems(control: ControlSet) -> None:
    plan_text = control.plan.read_text(encoding="utf-8")
    wrong_ids = _scores(control, "ids", _noise(control, 3), [*control.ids[:-1], "OTHER"])
    run = _run(control, wrong_ids, record=False)
    assert run.failed_checks == ["LIVE-002"]
    assert "live score file does not cover" in run.finding("LIVE-002").message.lower()
    tampered = _scores(control, "raw", np.arange(len(control.ids)) / 1000)
    run = _run(
        control, _scores(control, "live", _noise(control, 3)), record=False, control_inputs=tampered
    )
    assert "raw control inputs differ" in run.finding("LIVE-002").message
    _edit_plan(control, expected_scores={"2.0.0": "0" * 64})
    run = _run(control, _scores(control, "live", _noise(control, 3)), record=False)
    assert "not the one the plan records" in run.finding("LIVE-002").message
    control.plan.write_text(plan_text, encoding="utf-8")
    _edit_plan(control, expected_scores={"9.9.9": "0" * 64})
    run = _run(control, _scores(control, "live", _noise(control, 3)), record=False)
    assert "no expected scores for version 2.0.0" in run.finding("LIVE-002").message
    run = _run(
        control,
        _scores(control, "live", _noise(control, 3)),
        record=False,
        control_inputs=control.control,
    )
    assert run.finding("LIVE-002").details["control_inputs_checked"] is True


def test_tolerance_boundary(control: ControlSet) -> None:
    expected = control.expected["2.0.0"][1]
    tolerance = 2.0**-20
    _edit_plan(control, tolerance={"absolute": tolerance})
    at_limit = expected.copy()
    at_limit[0] += tolerance
    run = _run(control, _scores(control, "limit", at_limit), record=False)
    assert run.finding("LIVE-003").status.value == "pass"
    over = expected.copy()
    over[0] += 2 * tolerance
    run = _run(control, _scores(control, "over", over), record=False)
    assert run.failed_checks == ["LIVE-003"]
    assert run.finding("LIVE-003").details["records_over_tolerance"] == 1
    assert run.finding("LIVE-003").details["worst"][0]["row_id"] == control.ids[0]


def test_given_sd_and_rules(control: ControlSet) -> None:
    sd = 1e-8
    _edit_plan(control, sd=sd, tolerance={"absolute": 1e-3})
    expected = control.expected["2.0.0"][1]
    assert _run(control, _scores(control, "a", expected), k=0).verdict is QcVerdict.IN_CONTROL
    warn = _run(control, _scores(control, "b", expected + 2.5 * sd), k=1)
    assert warn.verdict is QcVerdict.IN_CONTROL
    assert warn.warnings == ("1_2s",)
    assert warn.finding("LIVE-004").status.value == "warn"
    reject = _run(control, _scores(control, "c", expected + 2.5 * sd), k=2)
    assert reject.verdict is QcVerdict.OUTSIDE_PLAN
    assert reject.rejections == ("2_2s",)
    assert "2_2s" in reject.finding("LIVE-004").message
    assert reject.mean == 0.0
    assert reject.sd == sd


def test_baseline_estimate_excludes_rejected_runs(control: ControlSet) -> None:
    _edit_plan(control, baseline_runs=5)
    for k in range(5):
        assert _run(control, _scores(control, f"b{k}", _noise(control, 10 + k)), k=k).notes
    bad = _run(control, _scores(control, "bad", _noise(control, 20, shift=5e-7)), k=5)
    assert bad.verdict is QcVerdict.OUTSIDE_PLAN
    assert bad.rejections[0] == "1_3s"
    after = _run(control, _scores(control, "after", _noise(control, 21)), k=6)
    assert after.verdict is QcVerdict.IN_CONTROL
    details = after.finding("LIVE-004").details
    assert details["baseline_runs"] == 5
    assert details["sd_floored"] is True
    assert details["sd"] == pytest.approx(sd_floor(1e-6, len(control.ids)))
    # Five baseline runs and this one; the rejected run is left out.
    assert len(details["z_history"]) == 6


def test_plan_without_qc(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="no deployment_qc block"):
        run_qc(
            plan=_plan_without_qc(tmp_path),
            scores=EXAMPLE / "qc" / "live-scores.parquet",
            expected=EXAMPLE / "qc" / "expected-2.0.0.parquet",
            model_version="2.0.0",
        )


def _plan_without_qc(tmp_path: Path) -> Path:
    text = (EXAMPLE / "change-plan.yaml").read_text(encoding="utf-8")
    path = tmp_path / "plain.yaml"
    path.write_text(text.split("# Deployment QC")[0], encoding="utf-8")
    return path


# Ledger ----------------------------------------------------------------------------------


def test_ledger_with_mixed_entry_kinds(control: ControlSet, tmp_path: Path) -> None:
    from medagentrx.engine import evaluate
    from tests.helpers.cases import make_case

    case = make_case(tmp_path / "case")
    ledger = tmp_path / "mixed.jsonl"
    from medagentrx.ledger import append

    append(ledger, evaluate(**case.kwargs(), n_replicates=200, now=T0 - dt.timedelta(days=1)))
    _run(control, _scores(control, "live", _noise(control, 30)), ledger=ledger)
    entries = read_entries(ledger)
    assert [e["kind"] for e in entries] == ["evaluation", "qc"]
    assert verify(ledger).ok
    history = summarize(entries)
    assert history.looks_used == 1
    assert entries[1]["touched_test_set"] is False
    tampered = dict(entries[1])
    tampered["qc"] = {**tampered["qc"], "bias": 0.0}
    ledger.write_text(json.dumps(entries[0]) + "\n" + json.dumps(tampered) + "\n", encoding="utf-8")
    assert "entry 1: content does not match its hash" in verify(ledger).problems


def test_qc_entry_refusals(control: ControlSet) -> None:
    ledger = control.plan.parent / "ledger.jsonl"
    stale = _run(control, _scores(control, "a", _noise(control, 40)), record=False, k=1)
    _run(control, _scores(control, "b", _noise(control, 41)), k=2)
    with pytest.raises(LedgerError, match="run it again with the current history"):
        append_qc(ledger, stale)
    earlier = _run(control, _scores(control, "c", _noise(control, 42)), record=False, k=0)
    with pytest.raises(LedgerError, match="check the system clock"):
        append_qc(ledger, earlier)
    entry = build_qc_entry(earlier, seq=0, prev_hash="0" * 64)
    assert entry["hash"] == entry_hash({k: v for k, v in entry.items() if k != "hash"})
    assert head_path_for(ledger).exists()


# CLI, API and Guard -----------------------------------------------------------------------


def test_cli_init_and_run(control: ControlSet, tmp_path: Path) -> None:
    init = runner.invoke(
        app,
        [
            "qc",
            "init",
            "--control-inputs",
            str(control.control),
            "--scores",
            str(control.expected["2.0.0"][0]),
            "--version",
            "2.0.0",
        ],
    )
    assert init.exit_code == 0, init.output
    assert "deployment_qc:" in init.stdout
    assert "disjointness checked against nothing" in init.stderr
    entry = runner.invoke(
        app,
        [
            "qc",
            "init",
            "--control-inputs",
            str(control.control),
            "--scores",
            str(control.expected["2.1.0"][0]),
            "--version",
            "2.1.0",
            "--plan",
            str(control.plan),
        ],
    )
    assert entry.stdout.startswith('    "2.1.0": ')
    bad = runner.invoke(
        app,
        [
            "qc",
            "init",
            "--control-inputs",
            str(control.expected["2.0.0"][0]),
            "--scores",
            str(tmp_path / "missing.parquet"),
            "--version",
            "2.0.0",
        ],
    )
    assert bad.exit_code == 3
    ledger, out = tmp_path / "ledger.jsonl", tmp_path / "out"
    base = [
        "qc",
        "run",
        str(control.plan),
        "--expected",
        str(control.expected["2.0.0"][0]),
        "--ledger",
        str(ledger),
        "--out",
        str(out),
    ]
    ok = runner.invoke(
        app,
        [
            *base,
            "--scores",
            str(_scores(control, "ok", _noise(control, 50))),
            "--model-version",
            "2.0.0",
            "--control-inputs",
            str(control.control),
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert "qc verdict: IN_CONTROL" in ok.output
    assert "NOTE Baseline run 1 of" in ok.output
    outside = runner.invoke(
        app,
        [
            *base,
            "--scores",
            str(_scores(control, "ok", _noise(control, 51))),
            "--model-version",
            "9.9.9",
            "--format",
            "json",
        ],
    )
    assert outside.exit_code == 2
    assert "FAIL LIVE-001" in outside.output
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (REPO_ROOT / "schema" / "qc-report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(report)
    malformed = tmp_path / "bad.csv"
    malformed.write_text("row_id,y_score\nx,abc\n", encoding="utf-8")
    error = runner.invoke(app, [*base, "--scores", str(malformed), "--model-version", "2.0.0"])
    assert error.exit_code == 3
    shown = runner.invoke(app, ["ledger", "show", str(ledger)])
    assert "qc: bias" in shown.output
    assert "qc: not measured" in shown.output
    assert "QC runs: 2 (1 outside the plan)" in shown.output


def test_api_and_guard(control: ControlSet, tmp_path: Path) -> None:
    result = qc(
        plan=control.plan,
        scores=_scores(control, "api", _noise(control, 60)),
        expected=control.expected["2.0.0"][0],
        model_version="2.0.0",
        ledger=tmp_path / "api.jsonl",
        out=tmp_path / "api-out",
        formats=["json", "md", "junit", "html"],
    )
    assert result.verdict is QcVerdict.IN_CONTROL
    assert result.exit_code == 0
    assert set(result.reports) == {"json", "md", "junit", "html"}
    assert "medagentrx qc" in result.reports["junit"].read_text(encoding="utf-8")
    assert "Levey-Jennings" in result.reports["html"].read_text(encoding="utf-8")
    private, public = tmp_path / "k.key", tmp_path / "k.pub"
    generate_key_pair(private, public)
    guard = Guard(
        control.plan,
        tmp_path / "guard.jsonl",
        previous=EXAMPLE / "previous.parquet",
        signing_key=private,
    )
    run = guard.qc(
        _scores(control, "g", _noise(control, 61)),
        control.expected["2.0.0"][0],
        model_version="2.0.0",
        now=T0,
    )
    assert run.verdict is QcVerdict.IN_CONTROL
    from medagentrx.signing import load_public_key

    assert verify(tmp_path / "guard.jsonl", public_key=load_public_key(public)).ok


# Reports, dashboard and document -----------------------------------------------------------


def test_reports_and_figures(control: ControlSet) -> None:
    run = _run(
        control, _scores(control, "x", _noise(control, 70, version="2.1.0")), version="2.1.0"
    )
    report = qc_report_dict(run)
    assert qc_figures(report) == []
    assert "All LIVE checks passed" not in render_qc_markdown(report)
    clean = _run(control, _scores(control, "y", _noise(control, 71)), k=1)
    report = qc_report_dict(clean)
    (figure,) = qc_figures(report)
    assert "before the baseline is complete" in figure.alt
    assert "All LIVE checks passed" in render_qc_markdown(report)


def test_dashboard_shows_qc(control: ControlSet, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from medagentrx.web.app import create_app, qc_charts

    _edit_plan(control, sd=1e-8, tolerance={"absolute": 1e-3})
    ledger = tmp_path / "web.jsonl"
    for k in range(3):
        _run(
            control,
            _scores(control, f"w{k}", control.expected["2.0.0"][1] + 3e-8 * k),
            ledger=ledger,
            k=k,
        )
    _run(
        control,
        _scores(control, "u", _noise(control, 80, version="2.1.0")),
        ledger=ledger,
        version="2.1.0",
        k=3,
    )
    charts = qc_charts(read_entries(ledger))
    assert [version for version, _ in charts] == ["2.0.0"]
    assert "fired 1_3s" in charts[0][1].alt
    client = TestClient(create_app(ledger=ledger))
    page = client.get("/qc")
    assert page.status_code == 200
    assert "Version 2.0.0" in page.text
    timeline = client.get("/timeline")
    assert timeline.text.count("<td>QC run</td>") == 4
    empty = TestClient(create_app(ledger=tmp_path / "none.jsonl")).get("/qc")
    assert "No QC run has been recorded yet" in empty.text


def test_document_has_a_qc_section(control: ControlSet) -> None:
    text = build_document(load_plan(control.plan))
    titles = [s.title for s in text.sections[1].sections]
    assert titles[-1] == "2.5 Deployment QC"
    checks = text.sections[-1].blocks[-1]
    assert "LIVE-004" in [row[0] for row in checks.rows]  # type: ignore[union-attr]
    bullets = text.sections[1].sections[-1].blocks[1]
    assert "Expected scores are recorded for versions 2.0.0, 2.1.0." in bullets.items  # type: ignore[union-attr]
    plain = build_document(
        load_plan(EXAMPLE / "change-plan.yaml").model_copy(update={"deployment_qc": None})
    )
    assert "2.5 Deployment QC" not in [s.title for s in plain.sections[1].sections]
    assert "LIVE-001" not in [row[0] for row in plain.sections[-1].blocks[-1].rows]  # type: ignore[union-attr]


def test_expected_file_must_cover_the_control_ids(control: ControlSet) -> None:
    short = _scores(control, "short", control.expected["2.0.0"][1][:-1], control.ids[:-1])
    _edit_plan(control, expected_scores={"2.0.0": sha256_file(short)})
    run = run_qc(
        plan=control.plan,
        scores=_scores(control, "live", _noise(control, 90)),
        expected=short,
        model_version="2.0.0",
        now=T0,
    )
    assert run.failed_checks == ["LIVE-002"]
    assert "expected score file does not cover" in run.finding("LIVE-002").message
    with pytest.raises(KeyError):
        run.finding("PERF-001")


def test_dashboard_opens_qc_reports(control: ControlSet, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from medagentrx.web.app import create_app

    result = qc(
        plan=control.plan,
        scores=_scores(control, "dash", _noise(control, 91)),
        expected=control.expected["2.0.0"][0],
        model_version="2.0.0",
        ledger=tmp_path / "dash.jsonl",
        out=tmp_path / "reports" / "run-1",
    )
    client = TestClient(create_app(ledger=tmp_path / "dash.jsonl", reports=tmp_path / "reports"))
    page = client.get(f"/versions/{result.ledger_entry['seq']}")
    assert "MedAgentRx deployment QC report" in page.text


def test_qc_scenarios_rerun_into_the_same_folder(tmp_path: Path) -> None:
    from medagentrx.demo import run_qc_scenario

    first = run_qc_scenario("qc-wrong-ids", tmp_path)
    second = run_qc_scenario("qc-wrong-ids", tmp_path)
    assert first.ok
    assert second.ok
    assert len(read_entries(tmp_path / "qc-wrong-ids" / "ledger.jsonl")) == 1

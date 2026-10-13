# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import dataclasses
import datetime as dt
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from typer.testing import CliRunner

from medagentrx.cli import app
from medagentrx.engine import Evaluation, evaluate
from medagentrx.errors import InputError
from medagentrx.ledger import append, read_entries
from medagentrx.report.build import budgets, figures, key_deltas
from medagentrx.report.figures import clean_svg, signed
from medagentrx.report.html import render_html
from medagentrx.report.json_report import report_dict
from medagentrx.report.junit import render_junit
from medagentrx.report.markdown import render_markdown
from medagentrx.report.writer import FORMATS, parse_formats, write_reports
from tests.conftest import REPO_ROOT
from tests.helpers.cases import Case, make_case
from tests.helpers.html_audit import assert_offline as _assert_offline

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
SCHEMA = json.loads(
    (REPO_ROOT / "src" / "medagentrx" / "report" / "report.schema.json").read_text(encoding="utf-8")
)
HOSTILE = '<script>alert("x")</script><img src=x onerror=alert(1)>'


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("case"))


@pytest.fixture(scope="module")
def evaluation(case: Case) -> Evaluation:
    return evaluate(**case.kwargs(), n_replicates=200, now=NOW)


@pytest.fixture(scope="module")
def report(evaluation: Evaluation) -> dict[str, Any]:
    return report_dict(evaluation, ledger={"seq": 0, "hash": "a" * 64})


def _by_id(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(c for c in report["checks"] if c["id"] == check_id)
    return found


def test_report_json_matches_published_schema(report: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    jsonschema.validate(report, SCHEMA)
    json.dumps(report, allow_nan=False)


def test_html_is_self_contained(report: dict[str, Any], evaluation: Evaluation) -> None:
    html = render_html(report)
    _assert_offline(html)
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert html.count("<svg") == 5
    assert "ACCEPTED" in html
    assert "not legal or regulatory advice" in html
    for check_id in [f.check_id for f in evaluation.findings]:
        assert f'id="{check_id}"' in html


def test_html_escapes_plan_and_data_strings(tmp_path: Path) -> None:
    def plan(p: dict[str, Any]) -> None:
        p["plan"]["device"] = HOSTILE
        p["impact_assessment"]["benefits"] = HOSTILE

    def meta(m: dict[str, Any]) -> None:
        m["version"] = "<b>9</b>"

    case = make_case(tmp_path, plan_edit=plan, meta_edit=meta)
    result = evaluate(**case.kwargs(), n_replicates=200, now=NOW)
    data = report_dict(result)
    data["checks"][0]["message"] = HOSTILE
    data["checks"][0]["details"] = {"note": HOSTILE}
    html = render_html(data)
    assert "<script" not in html.lower()
    assert "<img" not in html.lower()
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;9&lt;/b&gt;" in html
    _assert_offline(html)


def test_hostile_subgroup_labels_do_not_reach_the_markup(tmp_path: Path) -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    labels: list[object] = [HOSTILE if v else "plain" for v in rng.random(4000) < 0.5]

    def plan(p: dict[str, Any]) -> None:
        p["performance"]["subgroups"]["by"] = ["ward"]

    case = make_case(tmp_path, plan_edit=plan, test_extra={"ward": labels})
    result = evaluate(**case.kwargs(), n_replicates=200, now=NOW)
    html = render_html(report_dict(result))
    assert "<script" not in html.lower()
    _assert_offline(html)


def test_figures_are_deterministic(report: dict[str, Any]) -> None:
    first = [f.svg for f in figures(report)]
    second = [f.svg for f in figures(report)]
    assert first == second
    assert [f.key for f in figures(report)] == [
        "timeline",
        "forest",
        "calibration",
        "decision",
        "budgets",
    ]
    for figure in figures(report):
        assert figure.alt
        assert figure.svg.startswith("<svg")
        assert "xmlns" not in figure.svg
        assert "<metadata" not in figure.svg


def test_clean_svg() -> None:
    raw = (
        '<?xml version="1.0"?>\n<!DOCTYPE svg PUBLIC "x" "y">\n<!-- made -->\n'
        '<svg xmlns="a" xmlns:xlink="b" width="1"><metadata>m</metadata><path/></svg>'
    )
    assert clean_svg(raw) == '<svg role="img" focusable="false" width="1"><path/></svg>'
    assert signed(-0.0001, 2) == "+0.00"
    assert signed(-0.126, 2) == "-0.13"


def test_timeline_uses_ledger_history(
    tmp_path: Path, evaluation: Evaluation, report: dict[str, Any]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, evaluation)
    later = dataclasses.replace(
        evaluation,
        evaluated_at=NOW + dt.timedelta(days=100),
        candidate_version="2.2.0",
        ledger_entries_before=1,
    )
    append(ledger, later)
    timeline = figures(report, read_entries(ledger))[0]
    assert "2.1.0 ACCEPTED" in timeline.alt
    assert "2.2.0 ACCEPTED" in timeline.alt
    assert "Anchor AUROC" in timeline.alt


def test_timeline_marks_versions_without_auroc(report: dict[str, Any]) -> None:
    entries = [
        {"plan": {"id": "OTHER"}, "candidate_version": "9.9", "verdict": "ACCEPTED", "metrics": {}},
        {
            "plan": {"id": "SEPSIS-RISK-PCCP"},
            "candidate_version": "2.0.9",
            "verdict": "OUTSIDE_PLAN",
            "metrics": {},
        },
        {
            "plan": {"id": "SEPSIS-RISK-PCCP"},
            "candidate_version": "2.1.0",
            "verdict": "ACCEPTED",
            "metrics": {
                "auc": {
                    "candidate": {"auc": 0.8, "ci_lower": 0.79, "ci_upper": 0.81},
                    "anchor": {"auc": 0.78},
                }
            },
        },
    ]
    no_anchor = json.loads(json.dumps(report))
    _by_id(no_anchor, "PERF-001")["details"]["auc"].pop("anchor")
    timeline = figures(no_anchor, entries)[0]
    assert "9.9" not in timeline.alt
    assert "2.0.9 OUTSIDE_PLAN" in timeline.alt
    assert "Anchor AUROC 0.780" in timeline.alt
    alone = figures(no_anchor, entries[:2])
    assert alone[0].key == "forest"


def test_budgets_and_deltas(report: dict[str, Any]) -> None:
    assert budgets(report) == [
        ("Test-set looks", 1, 20, "1 of 20"),
        ("Alpha", pytest.approx(0.05 / 12), 0.05, "0.0042 of 0.05"),
        ("Updates", 1, 12, "1 of 12"),
    ]
    lines = key_deltas(report)
    assert lines[0].startswith("AUROC vs previous: +")
    assert any(line.startswith("Calibration slope") for line in lines)


def test_markdown_summary(report: dict[str, Any]) -> None:
    text = render_markdown(report)
    assert text.startswith("## MedAgentRx: PASS (ACCEPTED)")
    assert "| PERF-006 | warn |" in text
    assert "**Key numbers**" in text
    failing = json.loads(json.dumps(report))
    failing["verdict"] = "FAILED"
    _by_id(failing, "PERF-001")["status"] = "fail"
    _by_id(failing, "PERF-001")["message"] = "a | b"
    assert "| PERF-001 | fail | a \\| b |" in render_markdown(failing)
    passing = json.loads(json.dumps(report))
    for c in passing["checks"]:
        c["status"] = "pass"
    assert "All checks passed." in render_markdown(passing)


def test_junit_xml(report: dict[str, Any]) -> None:
    data = json.loads(json.dumps(report))
    _by_id(data, "PERF-001")["status"] = "fail"
    _by_id(data, "PERF-002")["status"] = "skipped"
    root = ET.fromstring(render_junit(data))  # noqa: S314  # our own output
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.get("tests") == "19"
    assert suite.get("failures") == "1"
    cases = suite.findall("testcase")
    assert len(cases) == 19
    by_name = {c.get("name", "").split()[0]: c for c in cases}
    failure = by_name["PERF-001"].find("failure")
    assert failure is not None
    assert failure.get("type") == "FAILED"
    assert by_name["PERF-002"].find("skipped") is not None
    warn = [c for c in cases if c.find("system-out") is not None]
    assert [c.get("name", "").split()[0] for c in warn] == ["PERF-006"]


def test_invalid_plan_reports(tmp_path: Path, case: Case) -> None:
    bad = tmp_path / "plan.yaml"
    bad.write_text("pccp_version: '7'\n", encoding="utf-8")
    result = evaluate(**dataclasses.replace(case, plan=bad).kwargs(), now=NOW)
    data = report_dict(result)
    jsonschema.validate(data, SCHEMA)
    html = render_html(data)
    assert "OUTSIDE PLAN" in html
    assert "<svg" not in html
    assert "The change plan is not valid." in render_markdown(data)
    junit = ET.fromstring(render_junit(data))  # noqa: S314  # our own output
    assert junit.find("testsuite").get("failures") == "1"  # type: ignore[union-attr]


def test_writer_and_formats(tmp_path: Path, evaluation: Evaluation) -> None:
    written = write_reports(tmp_path / "out", evaluation)
    assert sorted(written) == sorted(FORMATS)
    assert all(p.exists() for p in written.values())
    assert parse_formats("md, json,md") == ["md", "json"]
    with pytest.raises(InputError, match="unknown report format"):
        parse_formats("pdf")
    with pytest.raises(InputError, match="unknown report format"):
        parse_formats(" , ")


def test_cli_check_formats(tmp_path: Path, case: Case) -> None:
    args = [
        "check",
        str(case.plan),
        "--candidate",
        str(case.candidate),
        "--previous",
        str(case.previous),
        "--anchor",
        str(case.anchor),
        "--manifest",
        str(case.manifest),
        "--model-meta",
        str(case.model_meta),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
        "--out",
        str(tmp_path / "out"),
        "--replicates",
        "200",
        "--format",
        "md,junit",
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["junit.xml", "summary.md"]
    args[-1] = "pdf"
    assert CliRunner().invoke(app, args).exit_code == 3

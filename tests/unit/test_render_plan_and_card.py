# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from medagentrx import InputError, load_plan
from medagentrx.card import card_section, load_report, update_card
from medagentrx.cli import app
from medagentrx.document import Bullets, Document, Para, Section, Table, to_html, to_markdown
from medagentrx.engine import evaluate
from medagentrx.plan import parse_plan_text
from medagentrx.render_plan import build_document, describe_condition
from medagentrx.report.json_report import report_dict
from tests.conftest import EXAMPLE_PLAN, REPO_ROOT
from tests.helpers.cases import make_case
from tests.helpers.html_audit import assert_offline

runner = CliRunner()


@pytest.fixture(scope="module")
def document_md() -> str:
    return to_markdown(build_document(load_plan(EXAMPLE_PLAN)))


def test_document_covers_every_fda_component(document_md: str) -> None:
    for heading in (
        "## 1. Description of Modifications",
        "## 2. Modification Protocol",
        "### 2.1 Data management",
        "### 2.2 Re-training practices",
        "### 2.3 Performance evaluation",
        "### 2.4 Update procedures",
        "## 3. Impact Assessment",
        "## 4. Regulatory cross-reference (informative)",
        "## 5. Executable checks",
    ):
        assert heading in document_md


def test_document_covers_the_eu_cross_reference(document_md: str) -> None:
    for text in ("Article 43(4)", "Annex IV point 2(f)", "MDCG 2025-6", "MDR significant change"):
        assert text in document_md


def test_document_states_the_plan(document_md: str) -> None:
    plan = load_plan(EXAMPLE_PLAN)
    for fragment in (
        "age is at least 18",
        "site is one of A, B, C",
        "admission_date is between 2023-01-01 and 2026-12-31",
        plan.data_management.locked_test_set.sha256,
        "0.05 / 12 = 0.00417",
        "| Net benefit at thresholds 0.1, 0.2, 0.3 | Non-inferiority | previous | margin 0.005 |",
        "| Calibration slope | Within bounds | candidate only | [0.8, 1.2] |",
        "-0.02",
        "each tested at the full level as an intersection-union test",
        "| PERF-005 |",
        "| Silent performance loss in a subgroup | Subgroup criterion tested as an "
        "intersection-union test |",
        "not legal or regulatory advice",
    ):
        assert fragment in document_md, fragment
    assert "\u2014" not in document_md
    assert "\u2013" not in document_md


def _variant(edit: Any) -> str:
    data = yaml.safe_load(EXAMPLE_PLAN.read_text(encoding="utf-8"))
    edit(data)
    plan = parse_plan_text(yaml.safe_dump(data), source="v").plan
    return to_markdown(build_document(plan))


def test_document_variants() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["performance"]["alpha_spending"] = "alpha_investing"
        d["performance"]["subgroups"]["on_insufficient"] = "warn"
        d["performance"].pop("power")
        d["update_procedures"]["require_model_card_update"] = False
        d["modifications"][0].update(automatic=True, scope="local", description="Nightly run")
        d.pop("regulatory_map")

    text = _variant(edit)
    assert "Alpha-investing" in text
    assert "gives a warning" in text
    assert "A warning is given when power" not in text
    assert "not required by this plan" in text
    assert "| pipeline or agent, without a person | adapted per site | Nightly run |" in text
    assert "Plan reference" not in text

    def bare(d: dict[str, Any]) -> None:
        d["performance"].pop("subgroups")
        d["regulatory_map"] = {"eu": ["X"]}

    plain = _variant(bare)
    assert "Subgroups:" not in plain
    assert "Plan reference (FDA)" not in plain
    assert "| Plan reference (EU) | X |" in plain


def test_condition_descriptions() -> None:
    from pydantic import TypeAdapter

    from medagentrx.plan.models import Condition

    adapter: TypeAdapter[Any] = TypeAdapter(Condition)
    tree = adapter.validate_python(
        {
            "any": [
                {"field": "x", "op": "is_null"},
                {"field": "y", "op": "not_null"},
                {"not": {"field": "z", "op": "eq", "value": True}},
                {"not": {"all": [{"field": "w", "op": "lt", "value": 3}]}},
            ]
        }
    )
    described = describe_condition(tree)
    assert isinstance(described, Bullets)
    markdown = to_markdown(Document("t", [described], [], "f"))
    for text in (
        "At least one of the following:",
        "x is missing",
        "y is recorded",
        "Not: z is true",
        "Not the following:",
        "w is below 3",
    ):
        assert text in markdown


def test_html_document_is_escaped_and_offline(tmp_path: Path) -> None:
    data = yaml.safe_load(EXAMPLE_PLAN.read_text(encoding="utf-8"))
    data["plan"]["device"] = "<script>alert(1)</script>"
    data["impact_assessment"]["risks"][0]["risk"] = "<img src=x onerror=alert(1)>"
    plan = parse_plan_text(yaml.safe_dump(data), source="v").plan
    page = to_html(build_document(plan))
    assert "<script" not in page.lower()
    assert "<img" not in page.lower()
    assert "&lt;script&gt;" in page
    assert_offline(page)


def test_document_model_rendering() -> None:
    doc = Document(
        "Title",
        [Para("a | b")],
        [
            Section(
                "S",
                [
                    Table(["h"], [["x|y"]]),
                    Bullets([Bullets(["nested first"]), "item", Bullets(["child"])]),
                ],
                [Section("Sub", [Para("deep")])],
            )
        ],
        "foot",
    )
    md = to_markdown(doc)
    assert "| x\\|y |" in md
    assert "  - nested first" in md
    assert "### Sub" in md
    page = to_html(doc)
    assert "<li><ul><li>nested first</li></ul></li>" in page
    assert "<li>item<ul><li>child</li></ul></li>" in page
    assert "<h3>Sub</h3>" in page


def test_render_plan_command(tmp_path: Path) -> None:
    result = runner.invoke(app, ["render-plan", str(EXAMPLE_PLAN), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (
        (tmp_path / "pccp-document.md")
        .read_text(encoding="utf-8")
        .startswith("# Predetermined Change Control Plan: Sepsis risk score v2")
    )
    assert (tmp_path / "pccp-document.html").exists()
    only = runner.invoke(
        app, ["render-plan", str(EXAMPLE_PLAN), "--out", str(tmp_path / "md"), "--format", "md"]
    )
    assert only.exit_code == 0
    assert [p.name for p in (tmp_path / "md").iterdir()] == ["pccp-document.md"]
    bad = runner.invoke(
        app, ["render-plan", str(EXAMPLE_PLAN), "--out", str(tmp_path), "--format", "pdf"]
    )
    assert bad.exit_code == 3
    missing = runner.invoke(app, ["render-plan", "nope.yaml", "--out", str(tmp_path)])
    assert missing.exit_code == 3


# Model card ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def accepted_report(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    root = tmp_path_factory.mktemp("card")
    case = make_case(root)
    result = evaluate(**case.kwargs(), n_replicates=200)
    report = report_dict(result, ledger={"seq": 4, "hash": "c" * 64})
    path = root / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return case.plan, report


def test_card_section(accepted_report: tuple[Path, dict[str, Any]]) -> None:
    _, report = accepted_report
    section = card_section(report)
    assert section.startswith("<!-- medagentrx:begin version=2.1.0 -->\n## Version 2.1.0")
    assert "Ledger entry 4 (cccccccccccccccc)." in section
    assert "| AUROC (95% CI) |" in section
    assert " to " in section
    assert "AUROC change against previous" in section


def test_card_insert_replace_and_append(
    tmp_path: Path, accepted_report: tuple[Path, dict[str, Any]]
) -> None:
    plan_path, report = accepted_report
    plan = load_plan(plan_path)
    card = tmp_path / "MODEL_CARD.md"
    update_card(card, plan, report)
    update_card(card, plan, report)
    text = card.read_text(encoding="utf-8")
    assert text.startswith("# Model card: Sepsis risk score v2")
    assert text.count("begin version=2.1.0") == 1
    newer = json.loads(json.dumps(report))
    newer["candidate_version"] = "2.2.0"
    update_card(card, plan, newer)
    text = card.read_text(encoding="utf-8")
    assert text.index("version=2.1.0") < text.index("version=2.2.0")


def test_card_refusals(tmp_path: Path, accepted_report: tuple[Path, dict[str, Any]]) -> None:
    plan_path, report = accepted_report
    plan = load_plan(plan_path)
    failed = {**report, "verdict": "FAILED"}
    with pytest.raises(InputError, match="only accepted versions"):
        update_card(tmp_path / "c.md", plan, failed)
    with pytest.raises(InputError, match="different plan"):
        update_card(tmp_path / "c.md", load_plan(EXAMPLE_PLAN), report)
    (tmp_path / "dir.md").mkdir()
    with pytest.raises(InputError, match="regular file"):
        update_card(tmp_path / "dir.md", plan, report)
    no_card = json.loads(json.dumps(report))
    for c in no_card["checks"]:
        if c["id"] == "DOC-001":
            c["details"] = {}
    with pytest.raises(InputError, match="no model card data"):
        card_section(no_card)


def test_load_report_validation(
    tmp_path: Path, accepted_report: tuple[Path, dict[str, Any]]
) -> None:
    _, report = accepted_report
    good = tmp_path / "r.json"
    good.write_text(json.dumps(report), encoding="utf-8")
    assert load_report(good)["verdict"] == "ACCEPTED"
    bad = tmp_path / "bad.json"
    bad.write_text('{"verdict": NaN}', encoding="utf-8")
    with pytest.raises(InputError, match="not valid JSON"):
        load_report(bad)
    other = tmp_path / "other.json"
    other.write_text('{"verdict": "ACCEPTED"}', encoding="utf-8")
    with pytest.raises(InputError, match="not a MedAgentRx report"):
        load_report(other)


def test_published_report_schema_matches_package() -> None:
    published = (REPO_ROOT / "schema" / "report.schema.json").read_text(encoding="utf-8")
    packaged = (REPO_ROOT / "src" / "medagentrx" / "report" / "report.schema.json").read_text(
        encoding="utf-8"
    )
    assert published == packaged


def test_card_command(tmp_path: Path, accepted_report: tuple[Path, dict[str, Any]]) -> None:
    plan_path, report = accepted_report
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "card.md"
    result = runner.invoke(app, ["card", str(plan_path), "--report", str(path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    refused = runner.invoke(
        app, ["card", str(EXAMPLE_PLAN), "--report", str(path), "--out", str(out)]
    )
    assert refused.exit_code == 3

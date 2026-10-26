# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from typing import Any

import pytest

from medagentrx import check
from medagentrx.history import History
from medagentrx.ledger import read_entries
from medagentrx.preflight import Preflight, preflight
from medagentrx.signing import generate_key_pair, load_public_key
from medagentrx.stats.alpha import AlphaState
from tests.conftest import write_table
from tests.helpers.cases import Case, make_case


def _problems(result: Preflight) -> dict[str, str]:
    return {item.name: item.message for item in result.items if not item.ok}


def _accept(case: Case, ledger: Path, out: Path) -> None:
    result = check(**case.kwargs(), ledger=ledger, out=out, n_replicates=200, formats=["json"])
    assert result.verdict.value == "ACCEPTED"


def test_ready_without_a_ledger(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    result = preflight(**case.kwargs(), ledger=tmp_path / "ledger.jsonl")
    assert result.ready
    assert result.exit_code == 0
    names = [item.name for item in result.items]
    assert names == [
        "plan",
        "model_meta",
        "candidate",
        "previous",
        "anchor",
        "previous_rows",
        "anchor_rows",
        "test_set",
        "manifest",
        "ledger",
    ]
    data = result.to_dict()
    assert data["ready"] is True
    assert data["items"][-1]["message"] == "not found; check will create it"


def test_preflight_spends_no_look(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    for _ in range(3):
        assert preflight(**case.kwargs(), ledger=ledger).ready
    assert not ledger.exists()


def test_every_problem_is_reported(tmp_path: Path) -> None:
    case = make_case(
        tmp_path / "case",
        meta_edit=lambda m: m.update(modification_id="M9"),
        plan_edit=lambda p: p["data_management"]["locked_test_set"].update(sha256="0" * 64),
        manifest_edit=lambda t: t.__delitem__("age"),
    )
    write_table(
        case.previous,
        {"row_id": ["x1", "x2"], "y_true": [0, 1], "y_score": [0.2, 0.7]},
    )
    result = preflight(**case.kwargs())
    problems = _problems(result)
    assert not result.ready
    assert result.exit_code == 1
    assert "modification M9" in problems["model_meta"]
    assert "does not match the candidate's rows" in problems["previous_rows"]
    assert "not the locked test set" in problems["test_set"]
    assert "age" in problems["manifest"]
    assert "ledger" not in {item.name for item in result.items}


def test_invalid_plan_stops_early(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    case.plan.write_text("pccp_version: '0'\n", encoding="utf-8")
    result = preflight(**case.kwargs())
    assert [item.name for item in result.items] == ["plan"]
    assert not result.ready


def test_unreadable_files(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    case.candidate.write_text("row_id,y_true\nr1,0\n", encoding="utf-8")
    case.model_meta.write_text("- not a mapping\n", encoding="utf-8")
    problems = _problems(preflight(**case.kwargs()))
    assert "missing required column" in problems["candidate"]
    case = make_case(tmp_path / "second")
    case.previous.write_text("row_id,y_score\nr1,0.5\n", encoding="utf-8")
    second = _problems(preflight(**case.kwargs()))
    assert "y_true" in second["previous"]
    assert "previous_rows" not in second
    assert "must be a mapping" in problems["model_meta"]
    assert "test_set" not in problems


def test_plan_warnings_do_not_block(tmp_path: Path) -> None:
    case = make_case(
        tmp_path / "case",
        plan_edit=lambda p: p["performance"].pop("power", None),
    )
    result = preflight(**case.kwargs())
    assert result.ready
    assert isinstance(result.warnings, tuple)


def test_ledger_budget_is_reported(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    _accept(case, ledger, tmp_path / "r")
    result = preflight(**case.kwargs(), ledger=ledger)
    items = {item.name: item for item in result.items}
    assert items["ledger"].message == "intact, 1 entries"
    assert items["budget"].ok
    assert items["budget"].message.startswith("look 2 of 20; 1 of 12 updates released")


def test_ledger_that_fails_verification(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    _accept(case, ledger, tmp_path / "r")
    ledger.write_text(ledger.read_text(encoding="utf-8").replace("ACCEPTED", "FAILED"), "utf-8")
    problems = _problems(preflight(**case.kwargs(), ledger=ledger))
    assert problems["ledger"].startswith("fails verification")


def test_ledger_of_a_different_plan(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    _accept(case, ledger, tmp_path / "r")
    changed = make_case(tmp_path / "changed", plan_edit=lambda p: p.update(max_updates=11))
    problems = _problems(preflight(**changed.kwargs(), ledger=ledger))
    assert "this plan differs from it" in problems["ledger"]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            lambda p: p["data_management"]["locked_test_set"].update(max_evaluations=1),
            "all 1 looks at the locked test set are used",
        ),
        (lambda p: p.update(max_updates=1), "all 1 updates allowed by the plan are released"),
    ],
)
def test_spent_budgets(tmp_path: Path, edit: Any, message: str) -> None:
    case = make_case(tmp_path / "case", plan_edit=edit)
    ledger = tmp_path / "ledger.jsonl"
    _accept(case, ledger, tmp_path / "r")
    assert _problems(preflight(**case.kwargs(), ledger=ledger))["budget"] == message


def test_spent_alpha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    _accept(case, ledger, tmp_path / "r")
    history = History(alpha=AlphaState("bonferroni", 0.05, 12, 1, 0.05, 0.0))
    monkeypatch.setattr("medagentrx.ledger.summarize", lambda _: history)
    problems = _problems(preflight(**case.kwargs(), ledger=ledger))
    assert problems["budget"] == "the alpha budget is exhausted"


def test_signed_ledger_needs_the_right_key(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    _accept(case, ledger, tmp_path / "r")
    generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    key = load_public_key(tmp_path / "k.pub")
    problems = _problems(preflight(**case.kwargs(), ledger=ledger, public_key=key))
    assert "signature" in problems["ledger"] or "signed" in problems["ledger"]
    assert len(read_entries(ledger)) == 1

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import dataclasses
from pathlib import Path

import pytest

import medagentrx
from medagentrx import CheckResult, Verdict, check
from medagentrx.ledger import read_entries
from tests.helpers.cases import make_case


def test_public_names() -> None:
    for name in medagentrx.__all__:
        assert hasattr(medagentrx, name), name
    assert {"check", "Verdict", "load_plan"} <= set(medagentrx.__all__)


def test_check_records_and_reports(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    result = check(
        **case.kwargs(),
        ledger=tmp_path / "gov" / "ledger.jsonl",
        out=tmp_path / "report",
        n_replicates=200,
        formats=["json", "md"],
    )
    assert isinstance(result, CheckResult)
    assert result.verdict is Verdict.ACCEPTED
    assert result.exit_code == 0
    assert result.ledger_entry is not None
    assert result.ledger_entry["seq"] == 0
    assert sorted(result.reports) == ["json", "md"]
    assert len(read_entries(tmp_path / "gov" / "ledger.jsonl")) == 1


def test_check_with_invalid_plan(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    bad = tmp_path / "plan.yaml"
    bad.write_text("pccp_version: '0'\n", encoding="utf-8")
    inputs = dataclasses.replace(case, plan=bad).kwargs()
    result = check(**inputs, ledger=tmp_path / "ledger.jsonl", out=tmp_path / "r", formats=["json"])
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.ledger_entry is None
    assert result.exit_code == 2
    with pytest.raises(KeyError):
        result.evaluation.finding("NOPE-001")

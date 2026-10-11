# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from medagentrx import ledger as ledger_module
from medagentrx.cli import app
from medagentrx.engine import Evaluation, Verdict, evaluate
from medagentrx.errors import InputError
from medagentrx.ledger import (
    GENESIS,
    LedgerError,
    append,
    build_entry,
    entry_hash,
    head_path_for,
    load_history,
    read_entries,
    summarize,
    verify,
)
from tests.helpers.cases import Case, make_case

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
runner = CliRunner()


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("case"))


@pytest.fixture(scope="module")
def accepted(case: Case) -> Evaluation:
    result = evaluate(**case.kwargs(), n_replicates=200, now=NOW)
    assert result.verdict is Verdict.ACCEPTED
    return result


def _next(path: Path, evaluation: Evaluation, days: int, **changes: Any) -> Evaluation:
    """``evaluation`` as if made now from the ledger's current budgets."""
    history = summarize(read_entries(path))
    return dataclasses.replace(
        evaluation,
        evaluated_at=NOW + dt.timedelta(days=days),
        ledger_entries_before=history.entries,
        **changes,
    )


def _filled(tmp_path: Path, evaluation: Evaluation, n: int = 3) -> Path:
    path = tmp_path / "ledger.jsonl"
    for i in range(n):
        append(path, _next(path, evaluation, 100 * i))
    return path


def test_append_and_verify(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted)
    result = verify(path)
    assert result.ok, result.problems
    assert result.entries == 3
    entries = read_entries(path)
    assert [e["seq"] for e in entries] == [0, 1, 2]
    assert entries[0]["prev_hash"] == GENESIS
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert all(entry_hash(e) == e["hash"] for e in entries)
    head = json.loads(head_path_for(path).read_text(encoding="utf-8"))
    assert head == {"entries": 3, "head": entries[-1]["hash"]}
    assert entries[0]["metrics"]["auc"]["candidate"]["auc"] > 0.5
    assert "vs_anchor" in entries[0]["metrics"]


def test_empty_ledger(tmp_path: Path) -> None:
    path = tmp_path / "none.jsonl"
    assert verify(path).ok
    assert verify(path).head == GENESIS
    assert summarize([]).plan_id is None
    assert load_history(path).looks_used == 0


def test_summary_counts_looks_releases_and_alpha(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted)
    outside = _next(
        path, accepted, 400, verdict=Verdict.OUTSIDE_PLAN, touched_test_set=False, alpha_used=None
    )
    append(path, outside)
    history = load_history(path)
    assert history.plan_id == "SEPSIS-RISK-PCCP"
    assert history.plan_revision == 3
    assert history.looks_used == 3
    assert len(history.releases) == 3
    assert history.alpha is not None
    assert history.alpha.updates_tested == 3
    assert history.alpha.spent == pytest.approx(3 * 0.05 / 12)


def _rewrite(path: Path, transform: Any) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")


def test_tampered_entry_is_detected(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted)

    def edit(lines: list[str]) -> list[str]:
        first = json.loads(lines[0])
        first["verdict"] = "ACCEPTED" if first["verdict"] != "ACCEPTED" else "FAILED"
        return [json.dumps(first), *lines[1:]]

    _rewrite(path, edit)
    result = verify(path)
    assert not result.ok
    assert "entry 0: content does not match its hash" in result.problems


def test_rehashed_tamper_breaks_the_link(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted)

    def edit(lines: list[str]) -> list[str]:
        first = json.loads(lines[0])
        first["touched_test_set"] = False
        first["hash"] = entry_hash(first)
        return [json.dumps(first), *lines[1:]]

    _rewrite(path, edit)
    problems = verify(path).problems
    assert "entry 1: does not link to the entry before it" in problems


def test_truncation_is_detected(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted)
    _rewrite(path, lambda lines: lines[:-1])
    result = verify(path)
    assert not result.ok
    assert any("entries may have been removed" in p for p in result.problems)
    assert "head hash does not match the last entry" in result.problems


def test_reordering_is_detected(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted)
    _rewrite(path, lambda lines: [lines[1], lines[0], lines[2]])
    problems = verify(path).problems
    assert "entry 0: sequence number is 1" in problems


def test_missing_and_broken_head(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted, n=1)
    head = head_path_for(path)
    head.unlink()
    assert any("is missing" in p for p in verify(path).problems)
    head.write_text("not json", encoding="utf-8")
    assert any("cannot be read" in p for p in verify(path).problems)
    alternative = tmp_path / "elsewhere.head"
    alternative.write_text(
        json.dumps({"entries": 1, "head": read_entries(path)[0]["hash"]}), encoding="utf-8"
    )
    assert verify(path, head_path=alternative).ok


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{}\n\n", "line 2 is empty"),
        ("not json\n", "line 1 is not valid JSON"),
        ("[1, 2]\n", "line 1 is not a JSON object"),
        ('{"a": NaN}\n', "line 1 is not valid JSON"),
    ],
)
def test_malformed_lines(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(content, encoding="utf-8")
    result = verify(path)
    assert not result.ok
    assert message in result.problems[0]


def test_unknown_format_is_reported(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted, n=1)

    def edit(lines: list[str]) -> list[str]:
        entry = json.loads(lines[0])
        entry["format"] = 99
        return [json.dumps(entry)]

    _rewrite(path, edit)
    assert "entry 0: unknown format 99" in verify(path).problems


def test_append_refuses_a_broken_ledger(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted, n=2)
    _rewrite(path, lambda lines: lines[:-1])
    with pytest.raises(LedgerError, match="refusing to append"):
        append(path, _next(path, accepted, 0))
    with pytest.raises(LedgerError, match="fails verification"):
        load_history(path)


def test_stale_evaluation_is_refused(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted, n=1)
    with pytest.raises(LedgerError, match="evaluate again"):
        append(path, accepted)


def test_invalid_plan_evaluations_are_not_recorded(accepted: Evaluation) -> None:
    invalid = dataclasses.replace(accepted, plan_id=None, alpha_state=None)
    with pytest.raises(LedgerError, match="invalid plan"):
        build_entry(invalid, seq=0, prev_hash=GENESIS)


def test_lock_contention(
    tmp_path: Path, accepted: Evaluation, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    path.with_name("ledger.jsonl.lock").write_text("", encoding="utf-8")
    monkeypatch.setattr(ledger_module, "LOCK_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(LedgerError, match="another evaluation may be writing"):
        append(path, accepted)


def test_ledger_must_be_a_regular_file(tmp_path: Path, accepted: Evaluation) -> None:
    real = _filled(tmp_path, accepted, n=1)
    link = tmp_path / "link.jsonl"
    link.symlink_to(real)
    with pytest.raises(InputError, match="regular file"):
        read_entries(link)
    with pytest.raises(InputError, match="larger than the limit"):
        read_entries(real, max_bytes=10)


def test_looks_budget_enforced_through_the_ledger(tmp_path: Path) -> None:
    def small(plan: dict[str, Any]) -> None:
        plan["data_management"]["locked_test_set"]["max_evaluations"] = 2
        plan["max_updates"] = 12

    case = make_case(
        tmp_path / "c", plan_edit=small, meta_edit=lambda m: m.update(modification_id="M2")
    )
    path = tmp_path / "ledger.jsonl"
    verdicts = []
    for i in range(3):
        history = load_history(path)
        result = evaluate(
            **case.kwargs(), history=history, n_replicates=200, now=NOW + dt.timedelta(days=100 * i)
        )
        append(path, result)
        verdicts.append((result.verdict, result.failed_checks))
    assert verdicts[0] == (Verdict.ACCEPTED, [])
    assert verdicts[1] == (Verdict.ACCEPTED, [])
    assert verdicts[2] == (Verdict.OUTSIDE_PLAN, ["DATA-004"])
    assert load_history(path).looks_used == 2


def _check_args(case: Case, tmp_path: Path, out: str = "out") -> list[str]:
    return [
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
        str(tmp_path / out),
        "--replicates",
        "200",
    ]


def test_cli_check_writes_report_and_ledger(tmp_path: Path, case: Case) -> None:
    result = runner.invoke(app, _check_args(case, tmp_path))
    assert result.exit_code == 0, result.output
    assert "verdict: ACCEPTED" in result.output
    assert "WARN PERF-006" in result.output
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["report_schema"] == 1
    assert report["verdict"] == "ACCEPTED"
    assert report["ledger"]["seq"] == 0
    assert "not legal or regulatory advice" in report["disclaimer"]
    again = runner.invoke(app, _check_args(case, tmp_path, out="out2"))
    assert again.exit_code == 2
    assert "FAIL PLAN-004" in again.output
    shown = runner.invoke(app, ["ledger", "show", str(tmp_path / "ledger.jsonl")])
    assert "looks used: 1; releases: 1" in shown.output
    verified = runner.invoke(app, ["ledger", "verify", str(tmp_path / "ledger.jsonl")])
    assert verified.exit_code == 0
    assert verified.output.startswith("ok: 2 entries")


def test_cli_ledger_verify_fails_on_tamper(tmp_path: Path, accepted: Evaluation) -> None:
    path = _filled(tmp_path, accepted, n=2)
    _rewrite(path, lambda lines: lines[:-1])
    result = runner.invoke(app, ["ledger", "verify", str(path)])
    assert result.exit_code == 1
    assert "fails verification" in result.output
    blocked = runner.invoke(app, _check_args(make_case(tmp_path / "c2"), tmp_path))
    assert blocked.exit_code == 3
    assert "fails verification" in blocked.output


def test_cli_invalid_plan_is_not_recorded(tmp_path: Path, case: Case) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("pccp_version: '2.0'\n", encoding="utf-8")
    args = _check_args(case, tmp_path)
    args[1] = str(bad)
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "FAIL PLAN-001" in result.output
    assert not (tmp_path / "ledger.jsonl").exists()


def test_cli_input_error_exits_3(tmp_path: Path, case: Case) -> None:
    args = _check_args(case, tmp_path)
    args[args.index("--candidate") + 1] = str(tmp_path / "missing.csv")
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    assert "file not found" in result.output


def test_cli_ledger_show_and_verify_edge_cases(tmp_path: Path) -> None:
    empty = runner.invoke(app, ["ledger", "show", str(tmp_path / "none.jsonl")])
    assert empty.output.strip() == "the ledger is empty"
    target = tmp_path / "dir.jsonl"
    target.mkdir()
    assert runner.invoke(app, ["ledger", "show", str(target)]).exit_code == 3
    assert runner.invoke(app, ["ledger", "verify", str(target)]).exit_code == 3

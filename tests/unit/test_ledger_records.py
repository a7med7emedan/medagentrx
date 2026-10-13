# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from medagentrx.checks import Status
from medagentrx.cli import app
from medagentrx.engine import Evaluation, evaluate
from medagentrx.history import History, Release
from medagentrx.ledger import (
    LedgerError,
    append,
    entry_hash,
    head_path_for,
    load_history,
    read_entries,
    record,
    verify,
)
from medagentrx.report.json_report import report_dict
from medagentrx.signing import generate_key_pair, load_private_key
from tests.helpers.cases import Case, make_case

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
runner = CliRunner()


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("records"))


@pytest.fixture(scope="module")
def accepted(case: Case) -> Evaluation:
    return evaluate(**case.kwargs(), n_replicates=200, now=NOW)


def _ledger(tmp_path: Path, evaluation: Evaluation) -> Path:
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, evaluation)
    return ledger


def _rewrite(ledger: Path, entries: list[dict[str, Any]]) -> None:
    previous = "0" * 64
    for seq, entry in enumerate(entries):
        entry.update(seq=seq, prev_hash=previous)
        entry["hash"] = entry_hash(entry)
        previous = entry["hash"]
    ledger.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    head_path_for(ledger).write_text(json.dumps({"entries": len(entries), "head": previous}))


def test_release_and_card_records(accepted: Evaluation, tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, accepted)
    later = NOW + dt.timedelta(hours=1)
    release = record(ledger, "release", "2.1.0", now=later)
    assert release["evaluation"] == {"seq": 0, "hash": read_entries(ledger)[0]["hash"]}
    card = record(
        ledger,
        "card",
        "2.1.0",
        details={"card_sha256": "c" * 64},
        candidate_sha256=accepted.inputs["candidate"],
        now=later,
    )
    assert card["details"] == {"card_sha256": "c" * 64}
    assert verify(ledger).ok
    history = load_history(ledger)
    assert [r.version for r in history.deployed] == ["2.1.0"]
    assert history.card_versions == ("2.1.0",)
    assert history.looks_used == 1
    assert len(history.releases) == 1
    with pytest.raises(LedgerError, match="already has a release record"):
        record(ledger, "release", "2.1.0", now=later)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "deploy"}, "not a record kind"),
        ({"version": "9.9.9"}, "no accepted evaluation"),
        ({"candidate_sha256": "0" * 64}, "different candidate prediction file"),
        ({"now": NOW - dt.timedelta(days=1)}, "before the last ledger entry"),
        ({"now": dt.datetime(2026, 6, 1)}, "time zone"),
    ],
)
def test_record_refusals(
    accepted: Evaluation, tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    ledger = _ledger(tmp_path, accepted)
    args: dict[str, Any] = {"kind": "card", "version": "2.1.0", "now": NOW, **kwargs}
    with pytest.raises(LedgerError, match=message):
        record(ledger, args.pop("kind"), args.pop("version"), **args)


def test_the_clock_cannot_run_backwards(case: Case, accepted: Evaluation, tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, accepted)
    earlier = evaluate(
        **case.kwargs(), history=load_history(ledger), n_replicates=200, now=NOW - dt.timedelta(1)
    )
    with pytest.raises(LedgerError, match="check the system clock"):
        append(ledger, earlier)
    entries = read_entries(ledger) * 2
    entries = [dict(entries[0]), {**entries[1], "recorded_at": "2026-04-01T00:00:00+00:00"}]
    _rewrite(ledger, entries)
    assert "entry 1: recorded before the entry it follows" in verify(ledger).problems
    entries[1]["recorded_at"] = "yesterday"
    _rewrite(ledger, entries)
    assert "entry 1: recording time is missing or has no time zone" in verify(ledger).problems


def test_a_signed_ledger_stays_signed(accepted: Evaluation, tmp_path: Path) -> None:
    generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, accepted, signing_key=load_private_key(tmp_path / "k.key"))
    with pytest.raises(LedgerError, match="head is signed; appending needs the signing key"):
        record(ledger, "release", "2.1.0", now=NOW)


def test_doc_001_needs_the_previous_card(case: Case) -> None:
    accepted_before = History(
        plan_id=None, releases=(Release("2.0.0", NOW - dt.timedelta(days=60)),)
    )
    missing = evaluate(**case.kwargs(), history=accepted_before, n_replicates=200, now=NOW)
    finding = missing.finding("DOC-001")
    assert finding.status is Status.FAIL
    assert finding.details["missing_card_for"] == "2.0.0"
    assert "run medagentrx card with --ledger" in finding.message
    carded = History(releases=accepted_before.releases, card_versions=("2.0.0",))
    done = evaluate(**case.kwargs(), history=carded, n_replicates=200, now=NOW)
    assert done.finding("DOC-001").status is Status.PASS


def test_cli_records(case: Case, accepted: Evaluation, tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, accepted)
    report = tmp_path / "report.json"
    entry = read_entries(ledger)[0]
    report_json = report_dict(accepted, ledger={"seq": 0, "hash": entry["hash"]})
    report.write_text(json.dumps(report_json), encoding="utf-8")
    card_args = [
        "card",
        str(case.plan),
        "--report",
        str(report),
        "--out",
        str(tmp_path / "CARD.md"),
    ]
    result = runner.invoke(app, [*card_args, "--ledger", str(ledger)])
    assert result.exit_code == 0, result.output
    assert "recorded the card update for 2.1.0" in result.output
    released = runner.invoke(app, ["ledger", "release", str(ledger), "--version", "2.1.0"])
    assert released.exit_code == 0, released.output
    assert "recorded the release of 2.1.0 as entry 2" in released.output
    again = runner.invoke(app, ["ledger", "release", str(ledger), "--version", "2.1.0"])
    assert again.exit_code == 3
    shown = runner.invoke(app, ["ledger", "show", str(ledger)])
    assert "card of the accepted entry 0" in shown.output
    assert "release of the accepted entry 0" in shown.output
    assert "accepted: 1; in service: 1" in shown.output
    assert verify(ledger).ok


def test_append_refuses_record_kinds(accepted: Evaluation, tmp_path: Path) -> None:
    for kind in ("card", "release"):
        with pytest.raises(LedgerError, match="use record"):
            append(tmp_path / f"{kind}.jsonl", accepted, kind=kind)


def test_an_unsigned_ledger_cannot_start_signing(accepted: Evaluation, tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, accepted)
    generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    with pytest.raises(LedgerError, match="started without signatures"):
        record(
            ledger, "release", "2.1.0", now=NOW, signing_key=load_private_key(tmp_path / "k.key")
        )


def test_card_is_untouched_when_the_record_is_refused(
    case: Case, accepted: Evaluation, tmp_path: Path
) -> None:
    ledger = _ledger(tmp_path, accepted)
    record(ledger, "card", "2.1.0", now=NOW)
    entry = read_entries(ledger)[0]
    report = tmp_path / "report.json"
    report.write_text(json.dumps(report_dict(accepted, ledger={"seq": 0, "hash": entry["hash"]})))
    card = tmp_path / "CARD.md"
    card.write_text("# Card\n", encoding="utf-8")
    args = ["card", str(case.plan), "--report", str(report), "--out", str(card)]
    result = runner.invoke(app, [*args, "--ledger", str(ledger)])
    assert result.exit_code == 3
    assert "already has a card record" in result.output
    assert card.read_text(encoding="utf-8") == "# Card\n"


def test_malformed_heads_fail_verification(accepted: Evaluation, tmp_path: Path) -> None:
    generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, accepted, signing_key=load_private_key(tmp_path / "k.key"))
    head = head_path_for(ledger)
    good = json.loads(head.read_text())
    public = runner.invoke(
        app, ["ledger", "verify", str(ledger), "--public-key", str(tmp_path / "k.pub")]
    )
    assert public.exit_code == 0
    head.write_text(json.dumps({**good, "entries": [1]}))
    result = runner.invoke(
        app, ["ledger", "verify", str(ledger), "--public-key", str(tmp_path / "k.pub")]
    )
    assert result.exit_code == 1
    assert "the head is malformed" in result.output
    head.write_text("[1, 2]")
    assert verify(ledger).problems == (f"head file {head} is not a JSON object",)


def test_verify_checks_the_plan_key(case: Case, accepted: Evaluation, tmp_path: Path) -> None:
    fingerprint = generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, accepted, signing_key=load_private_key(tmp_path / "k.key"))
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        case.plan.read_text(encoding="utf-8") + f'ledger_signing_key_sha256: "{fingerprint}"\n',
        encoding="utf-8",
    )
    base = ["ledger", "verify", str(ledger), "--plan", str(plan)]
    missing = runner.invoke(app, base)
    assert missing.exit_code == 1
    assert "no key was given" in missing.output
    ok = runner.invoke(app, [*base, "--public-key", str(tmp_path / "k.pub")])
    assert ok.exit_code == 0, ok.output
    assert f"signature valid (key {fingerprint[:16]})" in ok.output
    generate_key_pair(tmp_path / "o.key", tmp_path / "o.pub")
    other = runner.invoke(app, [*base, "--public-key", str(tmp_path / "o.pub")])
    assert other.exit_code == 1
    assert "the plan pins signing key" in other.output

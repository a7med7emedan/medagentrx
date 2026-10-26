# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Command-line options and commands added for everyday and audit use."""

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from medagentrx import __version__, check
from medagentrx.cli import app
from medagentrx.errors import InputError
from medagentrx.exit_codes import ExitCode
from medagentrx.signing import generate_key_pair
from tests.conftest import EXAMPLE_DIR, EXAMPLE_PLAN
from tests.helpers.cases import Case, make_case

runner = CliRunner()


def _args(case: Case) -> list[str]:
    return [
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
    ]


def _check(case: Case, tmp_path: Path, *extra: str) -> Any:
    return runner.invoke(
        app,
        [
            *extra[:1],
            "check",
            *_args(case),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--out",
            str(tmp_path / "report"),
            "--replicates",
            "200",
            "--format",
            "json",
            *extra[1:],
        ],
    )


# Global options -------------------------------------------------------------------------


def test_version_flag() -> None:
    for flag in ("--version", "-V"):
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0
        assert result.output.strip() == f"medagentrx {__version__}"


def test_quiet_and_verbose_conflict() -> None:
    result = runner.invoke(app, ["--quiet", "--verbose", "version"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "cannot be used together" in result.output


def test_quiet_check_prints_nothing(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    result = _check(case, tmp_path, "--quiet")
    assert result.exit_code == 0
    assert result.output == ""


def test_verbose_check_prints_every_check(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    result = _check(case, tmp_path, "--verbose")
    assert result.exit_code == 0
    assert "PASS PLAN-001" in result.output
    assert "PASS DOC-001" in result.output or "N/A  DOC-001" in result.output


def test_check_json(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    result = _check(case, tmp_path, "--quiet", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["verdict"] == "ACCEPTED"
    assert data["exit_code"] == 0
    assert data["touched_test_set"] is True
    assert data["ledger_entry"]["seq"] == 0
    assert {c["id"] for c in data["checks"]} >= {"PLAN-001", "PERF-001"}
    assert set(data["reports"]) == {"json"}


def test_check_json_with_invalid_plan(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    case.plan.write_text("pccp_version: '0'\n", encoding="utf-8")
    result = _check(case, tmp_path, "--quiet", "--json")
    assert result.exit_code == ExitCode.OUTSIDE_PLAN
    assert json.loads(result.output)["ledger_entry"] is None


def test_validate_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("pccp_version: '0'\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(EXAMPLE_PLAN), str(bad), "--json"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    data = json.loads(result.output)
    assert data[0]["valid"] is True
    assert len(data[0]["fingerprint"]) == 64
    assert data[1]["valid"] is False
    quiet = runner.invoke(app, ["--quiet", "--verbose", "validate", str(EXAMPLE_PLAN)])
    assert quiet.exit_code == ExitCode.USAGE_ERROR
    verbose = runner.invoke(app, ["--verbose", "validate", str(EXAMPLE_PLAN)])
    assert "plan fingerprint" in verbose.output


# Notifications --------------------------------------------------------------------------


def test_check_notifies_on_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    def fake_send(url: str, notice: Any, *, fmt: str) -> str:
        sent.append((url, notice, fmt))
        return "hooks.slack.com"

    monkeypatch.setattr("medagentrx.notify.send", fake_send)
    case = make_case(tmp_path / "case", harm_site="C")
    result = _check(case, tmp_path, "--verbose", "--notify", "https://hooks.slack.com/x")
    assert result.exit_code == ExitCode.FAILED
    assert "notified: hooks.slack.com" in result.output
    assert "https://hooks.slack.com/x" not in result.output
    _, notice, fmt = sent[0]
    assert notice.verdict == "FAILED"
    assert "PERF-005" in notice.failed_checks
    assert fmt == "auto"


def test_good_verdict_notifies_only_about_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr("medagentrx.notify.send", lambda url, notice, fmt: sent.append(notice))
    monkeypatch.setenv("MEDAGENTRX_NOTIFY_URL", "https://example.org/hook")
    clean = make_case(tmp_path / "clean", plan_edit=lambda p: p["performance"].pop("power"))
    assert _check(clean, tmp_path / "a", "--quiet").exit_code == 0
    assert sent == []
    underpowered = make_case(tmp_path / "case")
    assert _check(underpowered, tmp_path / "b", "--quiet").exit_code == 0
    assert sent[0].verdict == "ACCEPTED"
    assert sent[0].warnings == ("PERF-006",)


def test_failed_notification_keeps_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> str:
        raise InputError("the webhook at example.org answered HTTP 500")

    monkeypatch.setattr("medagentrx.notify.send", broken)
    case = make_case(tmp_path / "case")
    result = runner.invoke(
        app,
        [
            "--quiet",
            "check",
            *_args(case),
            "--ledger",
            str(tmp_path / "l2.jsonl"),
            "--out",
            str(tmp_path / "r2"),
            "--replicates",
            "200",
            "--format",
            "json",
            "--notify",
            "https://example.org/h",
            "--notify-on",
            "always",
        ],
    )
    assert result.exit_code == 0
    assert "warning: notification not sent" in result.output


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--notify-on", "sometimes"], "--notify-on must be problems or always"),
        (["--notify-format", "email"], "--notify-format must be auto"),
        (["--notify", "http://example.org"], "must be an https:// URL"),
    ],
)
def test_bad_notification_options(tmp_path: Path, options: list[str], message: str) -> None:
    case = make_case(tmp_path / "case", n=400)
    result = _check(case, tmp_path, "--quiet", *options)
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert message in result.output
    assert not (tmp_path / "ledger.jsonl").exists()


# QC run ---------------------------------------------------------------------------------


def test_qc_run_json_and_verbose(tmp_path: Path) -> None:
    qc = EXAMPLE_DIR / "qc"
    args = [
        "qc",
        "run",
        str(EXAMPLE_PLAN),
        "--scores",
        str(qc / "live-scores.parquet"),
        "--expected",
        str(qc / "expected-2.0.0.parquet"),
        "--model-version",
        "2.0.0",
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
        "--out",
        str(tmp_path / "qc"),
        "--format",
        "json",
    ]
    result = runner.invoke(app, ["--quiet", *args, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["verdict"] == "IN_CONTROL"
    assert data["model_version"] == "2.0.0"
    assert data["ledger_entry"]["seq"] == 0
    assert [c["id"] for c in data["checks"]] == ["LIVE-001", "LIVE-002", "LIVE-003", "LIVE-004"]
    verbose = runner.invoke(app, ["--verbose", *args])
    assert "PASS LIVE-001" in verbose.output
    assert "N/A  LIVE-004" in verbose.output


# Preflight ------------------------------------------------------------------------------


def test_preflight_command(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    result = runner.invoke(app, ["preflight", *_args(case)])
    assert result.exit_code == 0
    assert "ready: medagentrx check can run" in result.output
    as_json = runner.invoke(app, ["preflight", *_args(case), "--json"])
    assert json.loads(as_json.output)["ready"] is True


def test_preflight_command_prints_plan_warnings(tmp_path: Path) -> None:
    case = make_case(
        tmp_path / "case",
        plan_edit=lambda p: p["data_management"]["locked_test_set"].update(max_evaluations=3),
    )
    result = runner.invoke(app, ["preflight", *_args(case)])
    assert result.exit_code == 0
    assert "warning: data_management.locked_test_set.max_evaluations" in result.output


def test_preflight_command_not_ready(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case", meta_edit=lambda m: m.update(modification_id="M9"))
    result = runner.invoke(app, ["preflight", *_args(case)])
    assert result.exit_code == 1
    assert "PROBLEM model_meta" in result.output
    assert result.output.rstrip().endswith("not ready")
    quiet = runner.invoke(app, ["--quiet", "preflight", *_args(case)])
    assert quiet.exit_code == 1
    assert "PROBLEM model_meta" in quiet.output
    assert "ok " not in quiet.output


def test_preflight_with_ledger_and_key(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case", plan_edit=lambda p: p["performance"].pop("power", None))
    ledger = tmp_path / "ledger.jsonl"
    check(**case.kwargs(), ledger=ledger, out=tmp_path / "r", n_replicates=200, formats=["json"])
    generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    result = runner.invoke(
        app,
        [
            "preflight",
            *_args(case),
            "--ledger",
            str(ledger),
            "--public-key",
            str(tmp_path / "k.pub"),
        ],
    )
    assert result.exit_code == 1
    assert "PROBLEM ledger" in result.output
    bad_key = runner.invoke(
        app, ["preflight", *_args(case), "--public-key", str(tmp_path / "missing.pub")]
    )
    assert bad_key.exit_code == ExitCode.USAGE_ERROR


# Explain --------------------------------------------------------------------------------


def test_explain() -> None:
    listing = runner.invoke(app, ["explain"])
    assert listing.exit_code == 0
    assert listing.output.count("\n") >= 24
    assert "PERF-005" in listing.output
    one = runner.invoke(app, ["explain", "perf-005", "LIVE-001"])
    assert one.exit_code == 0
    assert one.output.startswith("PERF-005: ")
    assert "LIVE-001: Live version is the released one" in one.output
    assert "checks/" in one.output
    data = json.loads(runner.invoke(app, ["explain", "DATA-001", "--json"]).output)
    assert data[0]["if_it_fails"] == "OUTSIDE_PLAN"
    assert data[0]["explanation"]
    assert len(json.loads(runner.invoke(app, ["explain", "--json"]).output)) == 23


def test_explain_unknown_check() -> None:
    result = runner.invoke(app, ["explain", "PERF-01", "XYZ"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "did you mean PERF-001" in result.output
    assert "unknown check XYZ\n" in result.output


# Plan diff ------------------------------------------------------------------------------


def _revised(tmp_path: Path, *, margin: str = "0.03", revision: str = "4") -> Path:
    text = EXAMPLE_PLAN.read_text(encoding="utf-8")
    text = text.replace("margin: 0.02}", f"margin: {margin}}}", 1)
    text = text.replace("revision: 3 ", f"revision: {revision} ", 1)
    path = tmp_path / "revised.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_plan_diff(tmp_path: Path) -> None:
    same = runner.invoke(app, ["plan-diff", str(EXAMPLE_PLAN), str(EXAMPLE_PLAN)])
    assert same.exit_code == 0
    assert "the plans mean the same" in same.output
    result = runner.invoke(app, ["plan-diff", str(EXAMPLE_PLAN), str(_revised(tmp_path))])
    assert result.exit_code == 1
    assert "~ performance.criteria[0].margin: 0.02 -> 0.03" in result.output
    assert "~ plan.revision: 3 -> 4" in result.output
    assert "warning" not in result.output
    data = json.loads(
        runner.invoke(
            app, ["plan-diff", str(EXAMPLE_PLAN), str(_revised(tmp_path)), "--json"]
        ).output
    )
    assert data["identical"] is False
    assert len(data["changes"]) == 2


def test_plan_diff_flags_a_missing_revision(tmp_path: Path) -> None:
    data = EXAMPLE_PLAN.read_text(encoding="utf-8").replace(
        "  - id: M2\n",
        "  - id: M3\n    type: fine_tune\n    automatic: true\n    scope: local\n  - id: M2\n",
        1,
    )
    revised = tmp_path / "r.yaml"
    revised.write_text(data, encoding="utf-8")
    result = runner.invoke(app, ["plan-diff", str(EXAMPLE_PLAN), str(revised)])
    assert result.exit_code == 1
    assert "+ modifications[M3]:" in result.output
    assert "plan.revision did not" in result.output
    removed = runner.invoke(app, ["plan-diff", str(revised), str(EXAMPLE_PLAN)])
    assert "- modifications[M3]:" in removed.output


def test_plan_diff_invalid_plan(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("pccp_version: '0'\n", encoding="utf-8")
    result = runner.invoke(app, ["plan-diff", str(EXAMPLE_PLAN), str(bad)])
    assert result.exit_code == ExitCode.USAGE_ERROR


# Ledger export --------------------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    case = make_case(tmp_path / "case")
    path = tmp_path / "ledger.jsonl"
    check(**case.kwargs(), ledger=path, out=tmp_path / "report", n_replicates=200, formats=["json"])
    return path


def test_ledger_export(ledger: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["ledger", "export", str(ledger)])
    assert result.exit_code == 0
    assert result.output.startswith("seq,recorded_at,kind")
    out = tmp_path / "x" / "ledger.json"
    written = runner.invoke(
        app, ["ledger", "export", str(ledger), "--format", "json", "-o", str(out)]
    )
    assert written.exit_code == 0
    assert f"wrote {out} (1 entries)" in written.output
    assert json.loads(out.read_text("utf-8"))[0]["verdict"] == "ACCEPTED"


def test_ledger_export_refusals(ledger: Path, tmp_path: Path) -> None:
    bad_format = runner.invoke(app, ["ledger", "export", str(ledger), "--format", "xlsx"])
    assert bad_format.exit_code == ExitCode.USAGE_ERROR
    target = tmp_path / "target.csv"
    target.write_text("", "utf-8")
    link = tmp_path / "link.csv"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available")
    linked = runner.invoke(app, ["ledger", "export", str(ledger), "-o", str(link)])
    assert linked.exit_code == ExitCode.USAGE_ERROR
    ledger.write_text(ledger.read_text("utf-8").replace("ACCEPTED", "FAILED"), "utf-8")
    broken = runner.invoke(app, ["ledger", "export", str(ledger)])
    assert broken.exit_code == 1
    assert "fails verification" in broken.output
    missing = runner.invoke(app, ["ledger", "export", str(tmp_path / "none" / "l.jsonl")])
    assert missing.exit_code == ExitCode.USAGE_ERROR
    assert "no such ledger" in missing.output


# Bundles --------------------------------------------------------------------------------


def test_bundle_commands(ledger: Path, tmp_path: Path) -> None:
    plan = ledger.parent / "case" / "change-plan.yaml"
    out = tmp_path / "evidence.zip"
    made = runner.invoke(
        app,
        [
            "bundle",
            "create",
            "--plan",
            str(plan),
            "--ledger",
            str(ledger),
            "--reports",
            str(tmp_path / "report"),
            "--out",
            str(out),
        ],
    )
    assert made.exit_code == 0, made.output
    assert "ledger of 1 entries" in made.output
    ok = runner.invoke(app, ["bundle", "verify", str(out)])
    assert ok.exit_code == 0
    assert ok.output.startswith("ok: ")
    as_json = json.loads(runner.invoke(app, ["bundle", "verify", str(out), "--json"]).output)
    assert as_json["ok"] is True
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(out) as old, zipfile.ZipFile(bad, "w") as new:
        for info in old.infolist():
            data = old.read(info)
            new.writestr(info.filename, b"edited" if info.filename.startswith("plan/c") else data)
    failed = runner.invoke(app, ["bundle", "verify", str(bad)])
    assert failed.exit_code == 1
    assert "does not check out" in failed.output
    not_zip = runner.invoke(app, ["bundle", "verify", str(plan)])
    assert not_zip.exit_code == ExitCode.USAGE_ERROR


def test_bundle_create_refusals(ledger: Path, tmp_path: Path) -> None:
    plan = ledger.parent / "case" / "change-plan.yaml"
    missing_plan = runner.invoke(
        app,
        ["bundle", "create", "--plan", str(tmp_path / "no.yaml"), "--ledger", str(ledger)],
    )
    assert missing_plan.exit_code == ExitCode.USAGE_ERROR
    ledger.write_text(ledger.read_text("utf-8").replace("ACCEPTED", "FAILED"), "utf-8")
    broken = runner.invoke(
        app,
        [
            "bundle",
            "create",
            "--plan",
            str(plan),
            "--ledger",
            str(ledger),
            "-o",
            str(tmp_path / "e.zip"),
        ],
    )
    assert broken.exit_code == 1
    assert "fails verification" in broken.output

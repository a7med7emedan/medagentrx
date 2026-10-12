# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Smoke and security tests of the read-only dashboard."""

import datetime as dt
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from medagentrx.cli import app as cli
from medagentrx.engine import evaluate
from medagentrx.guard import Guard
from medagentrx.ledger import append, load_history
from medagentrx.report.writer import write_reports
from medagentrx.web.app import SECURITY_HEADERS, bind_warning, create_app
from tests.helpers.cases import Case, make_case
from tests.helpers.html_audit import assert_offline

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> tuple[Case, Path, Path]:
    root = tmp_path_factory.mktemp("dash")

    def agent(plan: dict[str, object]) -> None:
        plan["modifications"][0]["automatic"] = True  # type: ignore[index]

    case = make_case(root / "case", plan_edit=agent)
    ledger = root / "ledger.jsonl"
    reports = root / "reports"
    guard = Guard(case.plan, ledger, previous=case.previous, n_replicates=200, seed=0)
    guard.submit(case.candidate, case.model_meta, manifest=case.manifest, now=NOW)
    evaluation = evaluate(**case.kwargs(), history=load_history(ledger), n_replicates=200, now=NOW)
    entry = append(ledger, evaluation)
    write_reports(reports / "v2.1.0", evaluation, entry=entry)
    return case, ledger, reports


@pytest.fixture(scope="module")
def client(workspace: tuple[Case, Path, Path]) -> TestClient:
    case, ledger, reports = workspace
    return TestClient(create_app(ledger=ledger, reports=reports, plan=case.plan))


@pytest.mark.parametrize("path", ["/", "/timeline", "/budgets", "/versions/0", "/versions/1"])
def test_pages_render_offline_with_security_headers(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert "set-cookie" not in response.headers
    html = response.text
    assert "<script" not in html.lower()
    if path != "/versions/1":
        assert "/static/style.css" in html
    else:
        assert_offline(html)


def test_overview_content(client: TestClient) -> None:
    html = client.get("/").text
    assert "Sepsis risk score v2" in html
    assert "Agent may make</dt><dd>M1" in html
    assert "guard" in html
    assert ">ACCEPTED<" in html
    assert "2 of 20" in html


def test_report_page_and_entry_fallback(client: TestClient) -> None:
    assert "MedAgentRx change report" in client.get("/versions/1").text
    entry = client.get("/versions/0").text
    assert "No report for this entry was found" in entry
    assert client.get("/versions/9").status_code == 404
    assert client.get("/versions/-1").status_code == 404
    assert client.get("/versions/x").status_code == 422


def test_timeline_and_budgets(client: TestClient) -> None:
    assert "<svg" in client.get("/timeline").text
    budgets = client.get("/budgets").text
    assert "Test-set looks 2 of 20" in budgets
    assert "Updates 1 of 12" in budgets


def test_read_only_and_no_docs(client: TestClient) -> None:
    for method in ("post", "put", "delete", "patch", "head"):
        response = getattr(client, method)("/")
        assert response.status_code == 405
        assert response.headers["X-Frame-Options"] == "DENY"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/static/style.css").headers["content-type"].startswith("text/css")
    assert client.get("/health").json() == {"status": "ok", "ledger_ok": True}


def test_without_plan_or_reports(workspace: tuple[Case, Path, Path], tmp_path: Path) -> None:
    _, ledger, _ = workspace
    bare = TestClient(create_app(ledger=ledger))
    assert "Decision ledger" in bare.get("/").text
    assert "Start the dashboard with" in bare.get("/budgets").text
    assert "No report for this entry" in bare.get("/versions/1").text
    empty = TestClient(create_app(ledger=tmp_path / "none.jsonl"))
    assert "The ledger is empty." in empty.get("/").text
    assert "No formal evaluation" in empty.get("/timeline").text


def test_broken_ledger_and_reports(workspace: tuple[Case, Path, Path], tmp_path: Path) -> None:
    _, ledger, reports = workspace
    copy = tmp_path / "ledger.jsonl"
    copy.write_text("\n".join(ledger.read_text().splitlines()[:-1]) + "\n")
    (tmp_path / "ledger.jsonl.head").write_text((ledger.parent / "ledger.jsonl.head").read_text())
    junk = tmp_path / "reports"
    (junk / "a").mkdir(parents=True)
    (junk / "a" / "report.json").write_text("{}")
    (junk / "b").mkdir()
    (junk / "b" / "report.json").symlink_to(reports / "v2.1.0" / "report.json")
    broken = TestClient(create_app(ledger=copy, reports=junk))
    assert "fails verification" in broken.get("/").text
    assert broken.get("/health").json()["ledger_ok"] is False


def test_bind_warning() -> None:
    assert bind_warning("127.0.0.1") is None
    assert bind_warning("::1") is None
    assert bind_warning("localhost") is None
    warning = bind_warning("0.0.0.0")  # noqa: S104
    assert warning is not None
    assert "no authentication" in warning
    assert bind_warning("dashboard.internal") is not None


def test_serve_command(workspace: tuple[Case, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    _, ledger, _ = workspace
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    result = CliRunner().invoke(cli, ["serve", "--ledger", str(ledger), "--host", "0.0.0.0"])  # noqa: S104
    assert result.exit_code == 0, result.output
    assert "WARNING: binding to 0.0.0.0" in result.output
    assert calls[0]["host"] == "0.0.0.0"  # noqa: S104
    assert calls[0]["server_header"] is False
    bad = CliRunner().invoke(cli, ["serve", "--ledger", str(ledger), "--plan", "missing.yaml"])
    assert bad.exit_code == 3
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    missing = CliRunner().invoke(cli, ["serve", "--ledger", str(ledger)])
    assert missing.exit_code == 3
    assert "medagentrx[web]" in missing.output

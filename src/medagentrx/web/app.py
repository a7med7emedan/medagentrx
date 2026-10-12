# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Read-only dashboard: plan overview, version timeline, reports and budgets.

The app only reads the ledger, the plan and a folder of reports. It has no
write route, no cookies, no authentication and no script, and it loads
nothing from other sites. It is meant for local use and binds to
127.0.0.1 by default. Reports are looked up by ledger entry number in an
index built at start-up, so no request path ever reaches the file system.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from jinja2 import Environment, PackageLoader, select_autoescape

from medagentrx import __version__
from medagentrx.card import load_report
from medagentrx.errors import MedAgentRxError
from medagentrx.ledger import read_entries, summarize, verify
from medagentrx.plan import load_plan
from medagentrx.plan.models import ChangePlan
from medagentrx.report.figures import budget_gauges, timeline
from medagentrx.report.html import render_html

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'none'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

_ENV = Environment(
    loader=PackageLoader("medagentrx.web", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)
_CSS = (resources.files("medagentrx.web") / "static" / "style.css").read_text(encoding="utf-8")


def bind_warning(host: str) -> str | None:
    """A loud warning when ``host`` exposes the dashboard beyond this machine."""
    if host == "localhost":
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return f"WARNING: binding to {host}. The dashboard has no authentication; keep it local."
    if address.is_loopback:
        return None
    return (
        f"WARNING: binding to {host} exposes the dashboard to other machines. "
        "It has no authentication and is meant for local use only."
    )


def _index_reports(folder: Path | None) -> dict[str, Path]:
    """Map ledger entry hash to report.json for every report under ``folder``."""
    index: dict[str, Path] = {}
    if folder is None:
        return index
    for path in sorted(folder.rglob("report.json")):
        if path.is_symlink():
            continue
        try:
            report = load_report(path)
        except MedAgentRxError:
            continue
        ledger = report.get("ledger") or {}
        if ledger.get("hash"):
            index[ledger["hash"]] = path
    return index


def create_app(*, ledger: Path, reports: Path | None = None, plan: Path | None = None) -> FastAPI:
    """Build the dashboard app.

    Args:
        ledger: The decision ledger.
        reports: Folder searched for ``report.json`` files at start-up.
        plan: The change plan, for budget limits and the drift budget.
    """
    app = FastAPI(
        title="MedAgentRx dashboard",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    change_plan: ChangePlan | None = load_plan(plan) if plan is not None else None
    report_index = _index_reports(reports)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method != "GET":
            return PlainTextResponse(
                "read-only dashboard", status_code=405, headers=SECURITY_HEADERS
            )
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    def page(template: str, **values: Any) -> HTMLResponse:  # noqa: ANN401
        entries = read_entries(ledger)
        context = {
            "version": __version__,
            "plan": change_plan,
            "ledger_path": ledger.name,
            "entries": entries,
            **values,
        }
        return HTMLResponse(_ENV.get_template(template).render(**context))

    @app.get("/static/style.css")
    def style() -> Response:
        return Response(_CSS, media_type="text/css")

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "ledger_ok": verify(ledger).ok})

    @app.get("/", response_class=HTMLResponse)
    def overview() -> HTMLResponse:
        entries = read_entries(ledger)
        result = verify(ledger)
        return page(
            "overview.html",
            history=summarize(entries) if result.ok else None,
            verification=result,
            latest=entries[-1] if entries else None,
        )

    @app.get("/timeline", response_class=HTMLResponse)
    def timeline_page() -> HTMLResponse:
        entries = [e for e in read_entries(ledger) if e.get("kind") == "evaluation"]
        points = []
        anchor_auc = None
        for e in entries:
            auc = (e.get("metrics") or {}).get("auc") or {}
            point: dict[str, Any] = {"version": e["candidate_version"], "verdict": e["verdict"]}
            if auc.get("candidate"):
                c = auc["candidate"]
                point.update(auc=c["auc"], ci_lower=c["ci_lower"], ci_upper=c["ci_upper"])
            if auc.get("anchor"):
                anchor_auc = auc["anchor"]["auc"]
            points.append(point)
        budget = change_plan.performance.cumulative_drift.max_drop_vs_anchor if change_plan else 0.0
        figure = None
        if any(p.get("auc") is not None for p in points):
            figure = timeline(points, anchor_auc=anchor_auc, budget=budget)
        return page("timeline.html", figure=figure)

    @app.get("/budgets", response_class=HTMLResponse)
    def budgets_page() -> HTMLResponse:
        history = summarize(read_entries(ledger))
        gauges: list[tuple[str, float, float, str]] = []
        if change_plan is not None:
            looks = change_plan.data_management.locked_test_set.max_evaluations
            alpha_total = change_plan.performance.alpha_total
            spent = history.alpha.spent if history.alpha else 0.0
            gauges = [
                ("Test-set looks", history.looks_used, looks, f"{history.looks_used} of {looks}"),
                ("Alpha", spent, alpha_total, f"{spent:.4f} of {alpha_total}"),
                (
                    "Updates",
                    len(history.releases),
                    change_plan.max_updates,
                    f"{len(history.releases)} of {change_plan.max_updates}",
                ),
            ]
        figure = budget_gauges(gauges) if gauges else None
        return page("budgets.html", history=history, figure=figure)

    @app.get("/versions/{seq}", response_class=HTMLResponse)
    def version_page(seq: int) -> HTMLResponse:
        entries = read_entries(ledger)
        if not 0 <= seq < len(entries):
            raise HTTPException(status_code=404, detail="no such ledger entry")
        entry = entries[seq]
        report_path = report_index.get(entry.get("hash", ""))
        if report_path is not None:
            return HTMLResponse(render_html(load_report(report_path), entries[: seq + 1]))
        return page("entry.html", entry=entry)

    return app

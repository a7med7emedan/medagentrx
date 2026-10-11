# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Self-contained HTML report.

The page makes no external request: styles are inline, figures are inline
SVG drawn by this package, there is no script, and a Content Security
Policy forbids loading anything. Every value is escaped by Jinja2.
"""

from __future__ import annotations

import json
import platform
import sys
from importlib import metadata
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from medagentrx.report.build import figures, key_deltas

VERDICT_TEXT = {
    "ACCEPTED": "The update is inside the plan and met every criterion.",
    "FAILED": "The update is inside the plan but did not meet its criteria. Do not release it.",
    "OUTSIDE_PLAN": "The update is not covered by the plan. It needs a new submission.",
}
_ENV = Environment(
    loader=PackageLoader("medagentrx.report", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _environment() -> list[tuple[str, str]]:
    rows = [
        ("Python", sys.version.split()[0]),
        ("Platform", f"{platform.system()} {platform.machine()}"),
    ]
    for package in ("numpy", "pyarrow", "matplotlib", "jinja2", "pydantic"):
        try:
            rows.append((package, metadata.version(package)))
        except metadata.PackageNotFoundError:  # pragma: no cover
            continue
    return rows


def render_html(report: dict[str, Any], entries: list[dict[str, Any]] | None = None) -> str:
    """Render the report as one HTML page."""
    entries = entries or []
    checks = []
    for item in report["checks"]:
        checks.append(
            {**item, "details_text": json.dumps(item["details"], indent=2, sort_keys=True)}
        )
    view = {**report, "checks": checks}
    ledger_rows = [
        {
            "seq": e.get("seq"),
            "recorded_at": str(e.get("recorded_at", ""))[:19],
            "candidate_version": e.get("candidate_version"),
            "verdict": e.get("verdict"),
            "failed": ", ".join(e.get("failed_checks", [])) or "none",
            "hash": str(e.get("hash", ""))[:16],
        }
        for e in entries[-5:]
    ]
    failed = ", ".join(c["id"] for c in report["checks"] if c["status"] == "fail")
    warnings = ", ".join(c["id"] for c in report["checks"] if c["status"] == "warn")
    return _ENV.get_template("report.html.j2").render(
        r=view,
        verdict_text=VERDICT_TEXT[report["verdict"]],
        failed=failed,
        warnings=warnings,
        deltas=key_deltas(report) if report["plan"]["id"] else [],
        figures=figures(report, entries),
        ledger_rows=ledger_rows,
        environment=_environment(),
    )

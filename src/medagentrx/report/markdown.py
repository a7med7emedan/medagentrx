# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Short Markdown summary for a pull request or merge request comment."""

from __future__ import annotations

from typing import Any

from medagentrx.report.build import key_deltas

ICON = {"ACCEPTED": "PASS", "FAILED": "FAIL", "OUTSIDE_PLAN": "OUTSIDE PLAN"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    """Verdict, failed checks and key deltas as Markdown."""
    plan = report["plan"]
    lines = [
        f"## MedAgentRx: {ICON[report['verdict']]} ({report['verdict']})",
        "",
        (
            f"Plan `{plan['id']}` revision {plan['revision']}. "
            f"Candidate `{report['candidate_version']}` ({report['modification_id']}) "
            f"replacing `{report['previous_version']}`."
            if plan["id"]
            else "The change plan is not valid."
        ),
        "",
    ]
    flagged = [c for c in report["checks"] if c["status"] in ("fail", "warn")]
    if flagged:
        lines += ["| Check | Status | Result |", "|---|---|---|"]
        lines += [f"| {c['id']} | {c['status']} | {_cell(c['message'])} |" for c in flagged]
    else:
        lines.append("All checks passed.")
    deltas = key_deltas(report) if plan["id"] else []
    if deltas:
        lines += ["", "**Key numbers**", ""] + [f"- {_cell(d)}" for d in deltas]
    lines += ["", f"<sub>{report['disclaimer']}</sub>", ""]
    return "\n".join(lines)

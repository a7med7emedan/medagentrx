# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Reports of a deployment QC run: JSON, HTML, Markdown and JUnit.

The formats match the update reports. The HTML page is self-contained and
makes no external request, and its Levey-Jennings chart is drawn from the
report data only, so the command line and the dashboard draw the same thing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from medagentrx.io.paths import safe_output_path
from medagentrx.qc import QcRun
from medagentrx.report.figures import SvgFigure, levey_jennings
from medagentrx.report.html import _ENV, _environment
from medagentrx.report.json_report import DISCLAIMER
from medagentrx.report.junit import render_junit
from medagentrx.report.writer import FORMATS

QC_REPORT_SCHEMA = 1
QC_VERDICT_TEXT = {
    "IN_CONTROL": (
        "The live system reproduced the expected scores of the released version within the "
        "plan's QC rules."
    ),
    "OUTSIDE_PLAN": (
        "The live system no longer behaves like the released version. This is an undeclared "
        "update: investigate before relying on its output."
    ),
}


def qc_report_dict(run: QcRun, *, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """The QC report as JSON-compatible data."""
    data: dict[str, Any] = {"report_schema": QC_REPORT_SCHEMA, **run.to_dict()}
    data["ledger"] = ledger
    data["disclaimer"] = DISCLAIMER
    return data


def chart_runs(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Runs for the Levey-Jennings chart: this version's history, then this run."""
    runs: list[dict[str, Any]] = [
        {"bias": h["bias"], "in_control": h["in_control"]} for h in report["history"]
    ]
    bias = report["qc"]["bias"]
    if isinstance(bias, int | float):
        fired = [*report["qc"]["rejections"], *report["qc"]["warnings"]]
        runs.append(
            {
                "bias": bias,
                "in_control": report["verdict"] == "IN_CONTROL",
                "current": True,
                "rules": fired,
            }
        )
    return runs


def qc_figures(report: dict[str, Any]) -> list[SvgFigure]:
    """The Levey-Jennings chart, when the run was measured."""
    runs = chart_runs(report)
    if not runs:
        return []
    return [levey_jennings(runs, mean=report["qc"]["mean"], sd=report["qc"]["sd"])]


def key_numbers(report: dict[str, Any]) -> list[str]:
    """One line per key number of the run."""
    qc = report["qc"]
    lines = []
    if isinstance(qc["bias"], int | float):
        lines.append(f"Run bias {qc['bias']:.3g} (mean of live minus expected score)")
    if isinstance(qc["max_abs_deviation"], int | float):
        lines.append(f"Largest record difference {qc['max_abs_deviation']:.3g}")
    if isinstance(qc["z"], int | float):
        lines.append(f"{qc['z']:+.2f} SD from the target mean")
    fired = [*qc["rejections"], *qc["warnings"]]
    if fired:
        lines.append(f"Rules fired: {', '.join(fired)}")
    return lines


def render_qc_html(report: dict[str, Any], entries: Sequence[dict[str, Any]] = ()) -> str:
    """Render the QC report as one HTML page."""
    checks = [
        {**item, "details_text": json.dumps(item["details"], indent=2, sort_keys=True)}
        for item in report["checks"]
    ]
    ledger_rows = [
        {
            "seq": e.get("seq"),
            "recorded_at": str(e.get("recorded_at", ""))[:19],
            "version": e.get("model_version"),
            "verdict": e.get("verdict"),
            "failed": ", ".join(e.get("failed_checks", [])) or "none",
            "hash": str(e.get("hash", ""))[:16],
        }
        for e in [e for e in entries if e.get("kind") == "qc"][-5:]
    ]
    return _ENV.get_template("qc.html.j2").render(
        r={**report, "checks": checks},
        verdict_text=QC_VERDICT_TEXT[report["verdict"]],
        failed=", ".join(c["id"] for c in report["checks"] if c["status"] == "fail"),
        warnings=", ".join(c["id"] for c in report["checks"] if c["status"] == "warn"),
        numbers=key_numbers(report),
        figures=qc_figures(report),
        ledger_rows=ledger_rows,
        environment=_environment(),
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_qc_markdown(report: dict[str, Any]) -> str:
    """Verdict, flagged checks and key numbers as Markdown."""
    plan = report["plan"]
    lines = [
        f"## MedAgentRx QC: {report['verdict']}",
        "",
        QC_VERDICT_TEXT[report["verdict"]],
        "",
        f"Plan `{plan['id']}` revision {plan['revision']}. Live version "
        f"`{report['model_version']}`; released version `{report['released_version']}`.",
        "",
    ]
    flagged = [c for c in report["checks"] if c["status"] in ("fail", "warn")]
    if flagged:
        lines += ["| Check | Status | Result |", "|---|---|---|"]
        lines += [f"| {c['id']} | {c['status']} | {_cell(c['message'])} |" for c in flagged]
    else:
        lines.append("All LIVE checks passed.")
    numbers = key_numbers(report)
    if numbers:
        lines += ["", "**Key numbers**", ""] + [f"- {n}" for n in numbers]
    lines += ["", f"<sub>{report['disclaimer']}</sub>", ""]
    return "\n".join(lines)


def write_qc_reports(
    out_dir: Path,
    run: QcRun,
    *,
    formats: Iterable[str] = tuple(FORMATS),
    entry: dict[str, Any] | None = None,
    entries: Sequence[dict[str, Any]] = (),
) -> dict[str, Path]:
    """Write each format of the QC report and return the paths by format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = None if entry is None else {"seq": entry["seq"], "hash": entry["hash"]}
    report = qc_report_dict(run, ledger=ledger)
    renderers = {
        "html": lambda: render_qc_html(report, entries),
        "json": lambda: json.dumps(report, indent=2, allow_nan=False) + "\n",
        "md": lambda: render_qc_markdown(report),
        "junit": lambda: render_junit(report),
    }
    written = {}
    for name in formats:
        target = safe_output_path(out_dir, FORMATS[name])
        target.write_text(renderers[name](), encoding="utf-8")
        written[name] = target
    return written

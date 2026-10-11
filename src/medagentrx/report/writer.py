# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Write the requested report formats inside the output directory."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from medagentrx.engine import Evaluation
from medagentrx.errors import InputError
from medagentrx.io.paths import safe_output_path
from medagentrx.report.html import render_html
from medagentrx.report.json_report import report_dict
from medagentrx.report.junit import render_junit
from medagentrx.report.markdown import render_markdown

FORMATS = {"html": "report.html", "json": "report.json", "md": "summary.md", "junit": "junit.xml"}


def parse_formats(text: str) -> list[str]:
    """Parse a comma-separated format list such as ``html,json``."""
    chosen = [f.strip() for f in text.split(",") if f.strip()]
    unknown = [f for f in chosen if f not in FORMATS]
    if unknown or not chosen:
        raise InputError(
            f"unknown report format(s): {', '.join(unknown) or text!r}; "
            f"choose from {', '.join(FORMATS)}"
        )
    return list(dict.fromkeys(chosen))


def write_reports(
    out_dir: Path,
    evaluation: Evaluation,
    *,
    formats: Iterable[str] = tuple(FORMATS),
    entry: dict[str, Any] | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    """Write each format and return the paths by format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = None if entry is None else {"seq": entry["seq"], "hash": entry["hash"]}
    report = report_dict(evaluation, ledger=ledger)
    renderers = {
        "html": lambda: render_html(report, entries),
        "json": lambda: json.dumps(report, indent=2, allow_nan=False) + "\n",
        "md": lambda: render_markdown(report),
        "junit": lambda: render_junit(report),
    }
    written = {}
    for name in formats:
        target = safe_output_path(out_dir, FORMATS[name])
        target.write_text(renderers[name](), encoding="utf-8")
        written[name] = target
    return written

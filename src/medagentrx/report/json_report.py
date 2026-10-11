# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Machine-readable report (``report.json``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medagentrx.engine import Evaluation
from medagentrx.io.paths import safe_output_path

REPORT_SCHEMA = 1
DISCLAIMER = (
    "MedAgentRx supports a quality management system. It is not legal or regulatory advice, "
    "does not replace your QMS or regulatory strategy, and its output is not itself a "
    "regulatory submission."
)


def report_dict(evaluation: Evaluation, *, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """The report as JSON-compatible data."""
    data: dict[str, Any] = {"report_schema": REPORT_SCHEMA, **evaluation.to_dict()}
    data["ledger"] = ledger
    data["disclaimer"] = DISCLAIMER
    return data


def write_json(
    out_dir: Path, evaluation: Evaluation, *, ledger: dict[str, Any] | None = None
) -> Path:
    """Write ``report.json`` inside ``out_dir`` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = safe_output_path(out_dir, "report.json")
    text = json.dumps(report_dict(evaluation, ledger=ledger), indent=2, allow_nan=False)
    target.write_text(text + "\n", encoding="utf-8")
    return target

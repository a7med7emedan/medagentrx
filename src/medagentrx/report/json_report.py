# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Machine-readable report (``report.json``)."""

from __future__ import annotations

from typing import Any

from medagentrx.engine import Evaluation

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

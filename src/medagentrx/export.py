# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Export the decision ledger as a table for audits and spreadsheets.

Each ledger entry becomes one row with the same columns, whatever its kind.
The CSV form protects spreadsheet users: a text cell that starts with ``=``,
``+``, ``-``, ``@``, a tab or a carriage return is prefixed with a quote, so
it is never run as a formula. The ledger itself stays the record; an export
is a copy for reading.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any, Literal

ExportFormat = Literal["csv", "json"]
COLUMNS = (
    "seq",
    "recorded_at",
    "kind",
    "plan_id",
    "plan_revision",
    "version",
    "previous_version",
    "modification_id",
    "verdict",
    "failed_checks",
    "warnings",
    "touched_test_set",
    "alpha_used",
    "qc_bias",
    "follows_entry",
    "hash",
    "prev_hash",
)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def ledger_rows(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One flat row per ledger entry, with the columns in ``COLUMNS``."""
    rows = []
    for entry in entries:
        plan = entry.get("plan") or {}
        qc = entry.get("qc") or {}
        follows = (entry.get("evaluation") or {}).get("seq")
        rows.append(
            {
                "seq": entry.get("seq"),
                "recorded_at": entry.get("recorded_at"),
                "kind": entry.get("kind"),
                "plan_id": plan.get("id"),
                "plan_revision": plan.get("revision"),
                "version": entry.get("candidate_version") or entry.get("model_version"),
                "previous_version": entry.get("previous_version"),
                "modification_id": entry.get("modification_id"),
                "verdict": entry.get("verdict"),
                "failed_checks": list(entry.get("failed_checks") or []),
                "warnings": list(entry.get("warnings") or []),
                "touched_test_set": entry.get("touched_test_set"),
                "alpha_used": (entry.get("alpha") or {}).get("used"),
                "qc_bias": qc.get("bias"),
                "follows_entry": follows,
                "hash": entry.get("hash"),
                "prev_hash": entry.get("prev_hash"),
            }
        )
    return rows


def _cell(value: Any) -> str:  # noqa: ANN401
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        value = ";".join(str(v) for v in value)
    text = str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text


def export_ledger(entries: Iterable[dict[str, Any]], fmt: ExportFormat) -> str:
    """The ledger as CSV or JSON text."""
    rows = ledger_rows(entries)
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_cell(row[c]) for c in COLUMNS])
    return buffer.getvalue()

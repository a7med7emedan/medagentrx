# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Model card sections built from an accepted report.

Each version gets one Markdown section between markers. Running the command
again for the same version replaces that section, so the card never holds
two copies. Only accepted versions are written, because only they may be
released.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema

from medagentrx.errors import InputError
from medagentrx.io.paths import resolve_input
from medagentrx.io.text import read_text_limited
from medagentrx.plan import plan_fingerprint
from medagentrx.plan.models import ChangePlan
from medagentrx.report.build import check
from medagentrx.report.figures import signed

MAX_REPORT_BYTES = 50_000_000


@cache
def report_schema(name: str = "report.schema.json") -> dict[str, Any]:
    """A published JSON Schema: ``report.schema.json`` or ``qc-report.schema.json``."""
    text = (resources.files("medagentrx.report") / name).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant {name}")


def load_report(path: str | Path) -> dict[str, Any]:
    """Read and validate the ``report.json`` of an update check.

    Raises:
        InputError: If the file is unsafe, not JSON, or does not match the schema.
    """
    return _load_json_report(path, "report.schema.json", "a MedAgentRx report")


def load_qc_report(path: str | Path) -> dict[str, Any]:
    """Read and validate the ``report.json`` of a deployment QC run.

    Raises:
        InputError: If the file is unsafe, not JSON, or does not match the schema.
    """
    return _load_json_report(path, "qc-report.schema.json", "a MedAgentRx QC report")


def _load_json_report(path: str | Path, schema_name: str, what: str) -> dict[str, Any]:
    real = resolve_input(path)
    text = read_text_limited(real, max_bytes=MAX_REPORT_BYTES)
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"{path}: not valid JSON ({exc})") from None
    validator = jsonschema.Draft202012Validator(report_schema(schema_name))
    errors = sorted(validator.iter_errors(data), key=str)
    if errors:
        raise InputError(
            f"{path}: not {what}",
            [
                f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                for e in errors[:10]
            ],
        )
    result: dict[str, Any] = data
    return result


def _markers(version: str) -> tuple[str, str]:
    return (
        f"<!-- medagentrx:begin version={version} -->",
        f"<!-- medagentrx:end version={version} -->",
    )


def card_section(report: dict[str, Any]) -> str:
    """Markdown section for the report's candidate version."""
    card = check(report, "DOC-001")["details"].get("card")
    if card is None:
        raise InputError("the report has no model card data (DOC-001 did not run)")
    version = report["candidate_version"]
    begin, end = _markers(version)
    low, high = card["auroc_ci"]
    rows = [
        ("AUROC (95% CI)", f"{card['auroc']:.3f} ({low:.3f} to {high:.3f})"),
        ("Calibration slope", f"{card['calibration_slope']:.3f}"),
        ("Calibration intercept", signed(card["calibration_intercept"], 3)),
        ("Brier score", f"{card['brier']:.4f}"),
        (f"Sensitivity at threshold {card['threshold']:g}", f"{card['sensitivity']:.3f}"),
        (f"Specificity at threshold {card['threshold']:g}", f"{card['specificity']:.3f}"),
        ("Locked test set", f"{card['n']} rows, {card['n_pos']} positive"),
    ]
    for name, test in check(report, "PERF-001")["details"].get("tests", {}).items():
        label = name.replace("vs_", "AUROC change against ")
        rows.append(
            (label, f"{signed(test['delta'], 4)} (lower bound {signed(test['ci_lower'], 4)})")
        )
    ledger = report.get("ledger") or {}
    entry = f" Ledger entry {ledger['seq']} ({ledger['hash'][:16]})." if ledger.get("hash") else ""
    lines = [
        begin,
        f"## Version {version}",
        "",
        (
            f"Accepted under plan {report['plan']['id']} revision {report['plan']['revision']} "
            f"as modification {report['modification_id']}, replacing {report['previous_version']}. "
            f"Evaluated {report['evaluated_at'][:10]}.{entry}"
        ),
        "",
        "| Measure | Value |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in rows),
        "",
        end,
    ]
    return "\n".join(lines) + "\n"


def update_card(card_path: Path, plan: ChangePlan, report: dict[str, Any]) -> Path:
    """Insert or replace the report's version section in the model card.

    Raises:
        InputError: If the report is not accepted, belongs to another plan, or
            the card path is unsafe.
    """
    if report["verdict"] != "ACCEPTED":
        raise InputError(
            f"only accepted versions go on the model card; this report is {report['verdict']}"
        )
    if report["plan"]["fingerprint"] != plan_fingerprint(plan):
        raise InputError("the report was produced under a different plan or plan revision")
    if card_path.is_symlink() or (card_path.exists() and not card_path.is_file()):
        raise InputError(f"{card_path}: the model card must be a regular file")
    section = card_section(report)
    begin, end = _markers(report["candidate_version"])
    if card_path.exists():
        text = card_path.read_text(encoding="utf-8")
    else:
        text = (
            f"# Model card: {plan.plan.device}\n\n"
            "Performance of each released version on the locked test set, "
            "recorded by MedAgentRx.\n\n"
        )
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.S)
    if pattern.search(text):
        text = pattern.sub(lambda _: section, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + section
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(text, encoding="utf-8")
    return card_path

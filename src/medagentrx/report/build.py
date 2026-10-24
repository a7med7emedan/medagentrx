# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Turn a report and the ledger into figures and view data.

Everything here reads the JSON-compatible report and ledger entries only,
so the command line, the model card and the dashboard draw the same thing.
"""

from __future__ import annotations

from typing import Any

from medagentrx.report.figures import (
    SvgFigure,
    budget_gauges,
    calibration_curves,
    decision_curves,
    forest,
    signed,
    timeline,
)

ASSESSED = {"pass", "fail", "warn"}


def check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    """One check of a report by identifier."""
    for item in report["checks"]:
        if item["id"] == check_id:
            result: dict[str, Any] = item
            return result
    raise KeyError(check_id)


def _timeline_points(report: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan_id = report["plan"]["id"]
    points = []
    for entry in entries:
        if entry.get("plan", {}).get("id") != plan_id or entry.get("kind", "evaluation") not in (
            "evaluation",
            "guard",
        ):
            continue
        auc = (entry.get("metrics") or {}).get("auc") or {}
        candidate = auc.get("candidate")
        point: dict[str, Any] = {"version": entry["candidate_version"], "verdict": entry["verdict"]}
        if candidate:
            point.update(
                auc=candidate["auc"], ci_lower=candidate["ci_lower"], ci_upper=candidate["ci_upper"]
            )
        points.append(point)
    if points:
        return points
    perf = check(report, "PERF-001")
    point = {"version": report["candidate_version"], "verdict": report["verdict"]}
    candidate = perf["details"].get("auc", {}).get("candidate")
    if candidate:
        point.update(
            auc=candidate["auc"], ci_lower=candidate["ci_lower"], ci_upper=candidate["ci_upper"]
        )
    return [point]


def _anchor_auc(report: dict[str, Any], entries: list[dict[str, Any]]) -> float | None:
    found = check(report, "PERF-001")["details"].get("auc", {}).get("anchor")
    if found:
        return float(found["auc"])
    for entry in reversed(entries):
        anchor = ((entry.get("metrics") or {}).get("auc") or {}).get("anchor")
        if anchor:
            return float(anchor["auc"])
    return None


def budgets(report: dict[str, Any]) -> list[tuple[str, float, float, str]]:
    """Budget use after this evaluation: test-set looks, alpha and released updates."""
    out: list[tuple[str, float, float, str]] = []
    looks = check(report, "DATA-004")["details"]
    if looks:
        used = looks["looks_used_before"] + (1 if report["touched_test_set"] else 0)
        out.append(
            (
                "Test-set looks",
                used,
                looks["max_evaluations"],
                f"{used} of {looks['max_evaluations']}",
            )
        )
    alpha = check(report, "LIFE-002")["details"]
    if alpha:
        spent = alpha["spent_before"] + (report["alpha"]["used"] or 0.0)
        total = alpha["alpha_total"]
        out.append(("Alpha", spent, total, f"{spent:.4f} of {total}"))
    updates = check(report, "PLAN-004")["details"]
    if updates:
        released = updates["released"] + (1 if report["verdict"] == "ACCEPTED" else 0)
        out.append(
            ("Updates", released, updates["max_updates"], f"{released} of {updates['max_updates']}")
        )
    return out


def figures(report: dict[str, Any], entries: list[dict[str, Any]] | None = None) -> list[SvgFigure]:
    """Every figure the report has data for, in a fixed order."""
    entries = entries or []
    out: list[SvgFigure] = []
    if report["plan"]["id"] is None:
        return out
    life = check(report, "LIFE-001")
    budget = life["details"].get("max_drop_vs_anchor", 0.0) if life["status"] in ASSESSED else 0.0
    points = _timeline_points(report, entries)
    if any(p.get("auc") is not None for p in points):
        out.append(timeline(points, anchor_auc=_anchor_auc(report, entries), budget=budget))
    subgroups = check(report, "PERF-005")
    if subgroups["status"] in ASSESSED and subgroups["details"].get("subgroups"):
        out.append(
            forest(subgroups["details"]["subgroups"], max_drop=subgroups["details"]["max_drop"])
        )
    calibration = check(report, "PERF-003")
    if calibration["status"] in ASSESSED and calibration["details"].get("curve"):
        out.append(
            calibration_curves(calibration["details"]["curve"], calibration["details"]["candidate"])
        )
    decision = check(report, "PERF-004")
    if decision["status"] in ASSESSED and decision["details"].get("curve"):
        out.append(decision_curves(decision["details"]["curve"]))
    gauges = budgets(report)
    if gauges:
        out.append(budget_gauges(gauges))
    return out


def key_deltas(report: dict[str, Any]) -> list[str]:
    """Short lines with the main numbers, for summaries."""
    lines = []
    perf = check(report, "PERF-001")
    for name, test in perf["details"].get("tests", {}).items():
        lines.append(
            f"AUROC {name.replace('_', ' ')}: {test['delta']:+.4f} "
            f"(lower bound {test['ci_lower']:+.4f}, margin -{test['margin']})"
        )
    calibration = check(report, "PERF-003")["details"].get("candidate")
    if calibration:
        lines.append(
            f"Calibration slope {calibration['slope']:.3f}, "
            f"intercept {signed(calibration['intercept'], 3)}"
        )
    life = check(report, "LIFE-001")["details"].get("test")
    if life:
        lines.append(
            f"Cumulative AUROC vs anchor: {life['delta']:+.4f} "
            f"(lower bound {life['ci_lower']:+.4f})"
        )
    return lines

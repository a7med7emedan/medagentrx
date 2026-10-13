# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""How far each statistical criterion is from its decision boundary.

The guard answers an agent with one bit for the whole plan. To add noise
once, every criterion that reads the locked test set is put on one scale:
its effect beyond the boundary, divided by its standard error, minus its
critical value. A criterion passes exactly when this slack is positive, so
the smallest slack decides the plan's statistical criteria together.

Standard errors always come from the locked test set. A slack computed on
the agent's own validation data then uses the same units, whatever the size
of that data, so the two can be compared as Thresholdout requires.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

from medagentrx.checks.registry import Finding, Status

_TINY = 1e-12
"""Smallest slack magnitude, so a criterion on its boundary keeps the sign of its decision."""

STATISTICAL_CHECKS = ("PERF-001", "PERF-002", "PERF-003", "PERF-004", "PERF-005", "LIFE-001")
"""Checks whose outcome depends on the labels of the locked test set."""


@dataclass(frozen=True)
class Slack:
    """One criterion's distance from its boundary.

    Attributes:
        effect: Estimate minus the boundary, positive on the passing side.
        se: Standard error of the estimate.
        critical: Critical value the standardised effect must exceed.
        passed: Whether the check passed this criterion.
    """

    effect: float
    se: float
    critical: float
    passed: bool

    def z(self) -> float:
        """Standardised slack: positive exactly when the criterion passed."""
        value = self.scaled(self.se)
        if math.isnan(value):  # pragma: no cover  # effects and errors are finite or infinite
            return -math.inf
        # Rounding must never contradict the check's own decision.
        return max(value, _TINY) if self.passed else min(value, -_TINY)

    def scaled(self, se: float) -> float:
        """Effect over ``se``, minus the critical value, without reference to the decision."""
        if not math.isfinite(self.effect):
            return self.effect
        if se <= 0.0 or not math.isfinite(se):
            return math.inf if self.passed else -math.inf
        return self.effect / se - self.critical


def _normal_critical(alpha: float) -> float:
    return NormalDist().inv_cdf(1.0 - alpha)


def _interval(effect: float, lower: float, margin: float, alpha: float, passed: bool) -> Slack:
    """Slack of an interval test: the standard error implied by its lower bound."""
    critical = _normal_critical(alpha)
    # A bootstrap percentile bound can sit on or above the estimate; keep the scale positive.
    se = abs(effect - lower) / critical if critical > 0 else 0.0
    return Slack(effect + margin, se, critical, passed)


def _auc_tests(prefix: str, tests: Mapping[str, Mapping[str, Any]]) -> dict[str, Slack]:
    return {
        f"{prefix}:{name}": Slack(
            float(t["delta"]) + float(t["margin"]),
            float(t["se"]),
            float(t["critical"]),
            bool(t["non_inferior"]),
        )
        for name, t in tests.items()
    }


def _slacks(finding: Finding) -> dict[str, Slack]:
    d = finding.details
    if finding.check_id == "PERF-001":
        return _auc_tests("PERF-001", d.get("tests", {}))
    if finding.check_id == "LIFE-001":
        return _auc_tests("LIFE-001", {"vs_anchor": d["test"]})
    if finding.check_id == "PERF-002":
        return {
            f"PERF-002:{name}": _interval(
                float(t["delta"]),
                float(t["ci_lower"]),
                float(t["margin"]),
                float(t["alpha"]),
                bool(t["non_inferior"]),
            )
            for name, t in d.get("tests", {}).items()
        }
    if finding.check_id == "PERF-004":
        alpha = (1.0 - float(d["level"])) / 2.0
        return {
            f"PERF-004:{name}": _interval(
                float(t["delta"]),
                float(t["ci_lower"]),
                float(t["margin"]),
                alpha,
                bool(t["non_inferior"]),
            )
            for name, t in d.get("tests", {}).items()
        }
    if finding.check_id == "PERF-003":
        out: dict[str, Slack] = {}
        candidate = d["candidate"]
        for metric, (low, high) in d["bounds"].items():
            name = metric.removeprefix("calibration_")
            value, se = float(candidate[name]), float(candidate[f"{name}_se"])
            out[f"PERF-003:{name}"] = Slack(
                min(value - low, high - value), se, 0.0, bool(low <= value <= high)
            )
        return out
    if finding.check_id == "PERF-005":
        out = {}
        for g in d.get("subgroups", []):
            key = f"PERF-005:{g['column']}={g['level']}"
            if g["status"] == "insufficient":
                if finding.status is Status.FAIL:
                    out[key] = Slack(-math.inf, 1.0, 0.0, False)
                continue
            out[key] = Slack(
                float(g["delta"]) + float(d["max_drop"]),
                float(g["se"]),
                float(g["critical"]),
                g["status"] == "pass",
            )
        return out
    return {}  # pragma: no cover  # only called for STATISTICAL_CHECKS


def slacks(findings: Iterable[Finding]) -> dict[str, Slack]:
    """Slack of every statistical criterion that was assessed, keyed by check and test."""
    out: dict[str, Slack] = {}
    for finding in findings:
        if finding.check_id not in STATISTICAL_CHECKS:
            continue
        if finding.status not in (Status.PASS, Status.FAIL, Status.WARN):
            continue
        if finding.check_id == "PERF-003" and not finding.details:
            out["PERF-003:fit"] = Slack(-math.inf, 1.0, 0.0, False)
            continue
        out.update(_slacks(finding))
    return out


def aggregate(holdout: Mapping[str, Slack]) -> float:
    """Smallest standardised slack on the locked test set; +inf with no criteria."""
    return min((s.z() for s in holdout.values()), default=math.inf)


def aggregate_against(validation: Mapping[str, Slack], holdout: Mapping[str, Slack]) -> float:
    """Smallest validation slack, standardised by the locked test set's errors.

    A criterion assessed on the locked test set but not on the validation data
    counts as failing there.
    """
    values = []
    for key, reference in holdout.items():
        own = validation.get(key)
        if own is None:
            values.append(-math.inf)
        elif reference.se > 0 and math.isfinite(reference.se):
            scale = reference.se
            values.append(Slack(own.effect, scale, reference.critical, own.passed).scaled(scale))
        else:
            values.append(own.z())
    return min(values, default=math.inf)

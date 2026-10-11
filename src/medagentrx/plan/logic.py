# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Cross-field rules that a JSON Schema cannot express.

Errors make the plan invalid. Warnings point at a plan that is valid but
probably not what its authors meant.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from medagentrx.plan.models import ChangePlan, NonInferiorityCriterion, WithinCriterion


@dataclass(frozen=True)
class Issue:
    """One finding about a plan."""

    level: Literal["error", "warning"]
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def check_logic(plan: ChangePlan) -> list[Issue]:
    """Return every cross-field issue in a structurally valid plan."""
    issues: list[Issue] = []
    issues += _duplicates([m.id for m in plan.modifications], "modifications", "modification id")
    issues += _duplicates(
        plan.data_management.forbid_overlap_on, "data_management.forbid_overlap_on", "key"
    )
    perf = plan.performance
    if perf.subgroups is not None:
        issues += _duplicates(perf.subgroups.by, "performance.subgroups.by", "column")

    keys: list[str] = []
    for criterion in perf.criteria:
        if isinstance(criterion, NonInferiorityCriterion):
            keys.append(f"{criterion.metric} non_inferiority")
        elif isinstance(criterion, WithinCriterion):  # pragma: no branch
            keys.append(f"{criterion.metric} within")
    issues += _duplicates(keys, "performance.criteria", "criterion")

    looks = plan.data_management.locked_test_set.max_evaluations
    if looks < plan.max_updates:
        issues.append(
            Issue(
                "warning",
                "data_management.locked_test_set.max_evaluations",
                f"{looks} looks cannot cover {plan.max_updates} updates",
            )
        )
    if not any(
        isinstance(c, NonInferiorityCriterion) and c.metric == "auroc" for c in perf.criteria
    ):
        issues.append(
            Issue("warning", "performance.criteria", "no AUROC non-inferiority criterion")
        )
    return issues


def _duplicates(values: list[str], path: str, what: str) -> list[Issue]:
    counts = Counter(values)
    return [
        Issue("error", path, f"duplicate {what} '{value}'") for value, n in counts.items() if n > 1
    ]

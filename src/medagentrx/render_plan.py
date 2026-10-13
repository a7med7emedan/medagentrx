# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Render the change plan as a PCCP document.

The document follows the three components of the FDA final guidance on
PCCPs for AI-enabled device software functions (4 December 2024):
Description of Modifications, Modification Protocol (data management,
re-training, performance evaluation, update procedures) and Impact
Assessment. It adds an informative cross-reference to the EU AI Act
(Article 43(4), Annex IV point 2(f)) and MDCG 2025-6, and a map from each
plan element to the executable check that enforces it.

The document and the gate read the same YAML, so they cannot drift apart.
"""

from __future__ import annotations

from medagentrx.checks import catalogue
from medagentrx.document import Bullets, Document, Para, Section, Table
from medagentrx.plan import plan_fingerprint
from medagentrx.plan.models import (
    AllCondition,
    AnyCondition,
    ChangePlan,
    Condition,
    LeafCondition,
    NonInferiorityCriterion,
    NotCondition,
    WithinCriterion,
)
from medagentrx.report.json_report import DISCLAIMER

MODIFICATION_TYPES = {
    "retrain_same_architecture": "Re-training with the same architecture on new data",
    "recalibrate": "Recalibration of predicted probabilities",
    "fine_tune": "Fine-tuning of the existing model",
}
METRICS = {
    "auroc": "AUROC",
    "sensitivity_at_threshold": "Sensitivity at the operating threshold",
    "specificity_at_threshold": "Specificity at the operating threshold",
    "net_benefit": "Net benefit",
    "calibration_slope": "Calibration slope",
    "calibration_intercept": "Calibration-in-the-large (intercept)",
}
OPS = {
    "eq": "is",
    "ne": "is not",
    "lt": "is below",
    "le": "is at most",
    "gt": "is above",
    "ge": "is at least",
    "in": "is one of",
    "not_in": "is not one of",
}


def _value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(_value(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def describe_condition(condition: Condition) -> Bullets | str:
    """Plain-English form of a condition tree."""
    if isinstance(condition, LeafCondition):
        if condition.op == "between":
            assert isinstance(condition.value, list)  # noqa: S101  # guaranteed by the model
            low, high = condition.value
            return f"{condition.field} is between {_value(low)} and {_value(high)}"
        if condition.op == "is_null":
            return f"{condition.field} is missing"
        if condition.op == "not_null":
            return f"{condition.field} is recorded"
        return f"{condition.field} {OPS[condition.op]} {_value(condition.value)}"
    if isinstance(condition, AllCondition):
        return Bullets(_group("All of the following:", condition.all_))
    if isinstance(condition, AnyCondition):
        return Bullets(_group("At least one of the following:", condition.any_))
    assert isinstance(condition, NotCondition)  # noqa: S101  # union is exhaustive
    inner = describe_condition(condition.not_)
    if isinstance(inner, str):
        return f"Not: {inner}"
    return Bullets(["Not the following:", inner])


def _group(lead: str, items: list[Condition]) -> list[str | Bullets]:
    described = [describe_condition(c) for c in items]
    flat = [d for d in described if isinstance(d, str)]
    nested = [d for d in described if isinstance(d, Bullets)]
    return [lead, Bullets([*flat, *nested])]


def _criteria_rows(plan: ChangePlan, alpha_k: str) -> list[list[str]]:
    rows = []
    for c in plan.performance.criteria:
        if isinstance(c, NonInferiorityCriterion):
            where = ""
            if c.at_thresholds:
                where = " at thresholds " + ", ".join(f"{t:g}" for t in c.at_thresholds)
            rows.append(
                [
                    METRICS[c.metric] + where,
                    "Non-inferiority",
                    ", ".join(c.vs),
                    f"margin {c.margin:g}",
                    f"one-sided alpha {alpha_k}",
                ]
            )
        elif isinstance(c, WithinCriterion):  # pragma: no branch
            rows.append(
                [
                    METRICS[c.metric],
                    "Within bounds",
                    "candidate only",
                    f"[{c.bounds[0]:g}, {c.bounds[1]:g}]",
                    "point estimate",
                ]
            )
    return rows


def _alpha_text(plan: ChangePlan) -> tuple[str, str]:
    perf = plan.performance
    if perf.alpha_spending == "bonferroni":
        per = perf.alpha_total / plan.max_updates
        return (
            f"{per:.5f}",
            f"Bonferroni: each update is tested at alpha {perf.alpha_total:g} / {plan.max_updates} "
            f"= {per:.5f}, which controls the family-wise error rate over the life of the plan.",
        )
    return (
        "from alpha-investing",
        "Alpha-investing (Foster and Stine 2008) with total alpha "
        + f"{perf.alpha_total:g}: the level of each test follows from the remaining "
        + "wealth. This controls the marginal false discovery rate.",
    )


def _performance_notes(plan: ChangePlan) -> list[str | Bullets]:
    perf = plan.performance
    drift = perf.cumulative_drift.max_drop_vs_anchor
    notes: list[str | Bullets] = [
        "Bio-creep guard: the lower bound of the AUROC difference against the anchor "
        f"must stay at or above -{drift:g}.",
    ]
    if perf.subgroups:
        rule = perf.subgroups
        outcome = "fails the update" if rule.on_insufficient == "fail" else "gives a warning"
        notes.append(
            f"Subgroups: for each level of {', '.join(rule.by)}, the AUROC may not drop more "
            f"than {rule.max_drop:g} against the previous version, "
            + (
                "each tested at the full level as an intersection-union test. "
                if rule.multiplicity == "none"
                else f"with {rule.multiplicity.capitalize()} correction. "
            )
            + f"A subgroup with fewer than "
            f"{rule.min_events} positives or negatives is insufficient evidence and {outcome}."
        )
    if perf.power:
        notes.append(
            "A warning is given when power to detect the AUROC margin is below "
            f"{perf.power.min_power:g}."
        )
    notes.append(
        "Statistical methods: paired DeLong test, Tango score interval, logistic "
        "recalibration, paired stratified bootstrap for net benefit."
    )
    return notes


def build_document(plan: ChangePlan) -> Document:
    """The PCCP document of a plan."""
    header = plan.plan
    dm = plan.data_management
    perf = plan.performance
    alpha_k, alpha_text = _alpha_text(plan)

    description = Section(
        "1. Description of Modifications",
        [
            Para(
                "The modifications below are the only changes this plan allows. Any other "
                "change, including a new architecture or a new intended use, is outside the "
                "plan and needs a new submission."
            ),
            Table(
                ["Id", "Modification", "Triggered by", "Scope", "Notes"],
                [
                    [
                        m.id,
                        MODIFICATION_TYPES[m.type],
                        "pipeline or agent, without a person" if m.automatic else "a person",
                        "the same for all sites" if m.scope == "global" else "adapted per site",
                        m.description or "",
                    ]
                    for m in plan.modifications
                ],
            ),
            Bullets(
                [
                    f"At most {plan.max_updates} updates under this plan.",
                    f"At most {plan.update_frequency.count} update(s) per "
                    f"{plan.update_frequency.max_per}.",
                    f"Every update is compared with its predecessor and with the anchor, "
                    f"version {plan.anchor_version}.",
                ]
            ),
        ],
    )

    inclusion = describe_condition(dm.training_inclusion)
    protocol = Section(
        "2. Modification Protocol",
        [Para("The protocol has four elements, as in the FDA guidance.")],
        [
            Section(
                "2.1 Data management",
                [
                    Para("Every row of the training data must meet these criteria:"),
                    inclusion if isinstance(inclusion, Bullets) else Bullets([inclusion]),
                    Bullets(
                        [
                            "Locked test set fingerprint: " + dm.locked_test_set.sha256 + ".",
                            f"The locked test set may be evaluated at most "
                            f"{dm.locked_test_set.max_evaluations} times over the life of "
                            "the plan, counting failed evaluations.",
                            "No value of " + ", ".join(dm.forbid_overlap_on) + " may appear in "
                            "both training and test data.",
                        ]
                    ),
                ],
            ),
            Section(
                "2.2 Re-training practices",
                [
                    Bullets(
                        [f"{m.id}: {MODIFICATION_TYPES[m.type]}." for m in plan.modifications]
                        + [
                            "Each update records the SHA-256 of its architecture definition, its "
                            "training manifest and its intended-use statement.",
                            "Model predictions on the locked test set are the only artefact "
                            "evaluated; model binaries are never loaded.",
                        ]
                    )
                ],
            ),
            Section(
                "2.3 Performance evaluation",
                [
                    Para(alpha_text),
                    Para(
                        "Operating threshold for sensitivity and specificity: "
                        f"{perf.operating_threshold:g}."
                    ),
                    Table(
                        ["Metric", "Test", "Compared with", "Limit", "Level"],
                        _criteria_rows(plan, alpha_k),
                    ),
                    Bullets(_performance_notes(plan)),
                ],
            ),
            Section(
                "2.4 Update procedures",
                [
                    Bullets(
                        [
                            (
                                "The model card is updated with each released version's "
                                "performance."
                                if plan.update_procedures.require_model_card_update
                                else "A model card update is not required by this plan."
                            ),
                            "User communication: " + plan.update_procedures.user_communication,
                            "Real-world monitoring: "
                            + plan.update_procedures.real_world_monitoring,
                            "Every evaluation, including failed ones, is written to a "
                            "hash-chained decision ledger.",
                        ]
                    )
                ],
            ),
        ],
    )

    impact = Section(
        "3. Impact Assessment",
        [
            Para("Benefits: " + plan.impact_assessment.benefits),
            Table(
                ["Risk", "Mitigation"],
                [[r.risk, r.mitigation] for r in plan.impact_assessment.risks],
            ),
        ],
    )

    mapping_rows = [
        ["FDA PCCP: Description of Modifications", "Section 1"],
        ["FDA PCCP: Modification Protocol (four elements)", "Section 2"],
        ["FDA PCCP: Impact Assessment", "Section 3"],
        [
            "EU AI Act Article 43(4): pre-determined changes are not a substantial modification",
            "Sections 1 and 2",
        ],
        [
            "EU AI Act Annex IV point 2(f): description of pre-determined changes and "
            "their assessment",
            "Sections 1 to 3",
        ],
        [
            "MDCG 2025-6: predetermined changes under the AI Act; MDR significant change "
            "assessed separately",
            "Sections 1 to 3",
        ],
    ]
    if plan.regulatory_map:
        if plan.regulatory_map.fda:
            mapping_rows.append(["Plan reference (FDA)", plan.regulatory_map.fda])
        mapping_rows += [["Plan reference (EU)", ref] for ref in plan.regulatory_map.eu]
    regulatory = Section(
        "4. Regulatory cross-reference (informative)",
        [
            Para(
                "This map is informative. It does not establish that the plan meets any "
                "regulation; that assessment belongs to the manufacturer and the reviewer."
            ),
            Table(["Requirement", "Where it is addressed"], mapping_rows),
        ],
    )

    checks = Section(
        "5. Executable checks",
        [
            Para(
                "Each update is checked automatically against this plan. A failed check that "
                "breaks the plan gives OUTSIDE_PLAN; any other failed check gives FAILED."
            ),
            Table(
                ["Check", "What it enforces", "If it fails", "Cross-reference"],
                [
                    [s.check_id, s.title, s.breaks.value.replace("_", " "), s.cross_reference]
                    for s in catalogue()
                ],
            ),
        ],
    )

    intro: list[Para | Bullets | Table] = [
        Table(
            ["Field", "Value"],
            [
                ["Device", header.device],
                ["Plan", f"{header.id}, revision {header.revision}"],
                ["Authorised", header.authorised.isoformat()],
                ["Anchor version", plan.anchor_version],
                ["Intended-use statement SHA-256", header.intended_use_sha256],
                ["Plan fingerprint", plan_fingerprint(plan)],
            ],
        ),
        Para(
            "This document is produced from the plan file that also drives the automated "
            "gate, so the two cannot differ."
        ),
    ]
    return Document(
        title=f"Predetermined Change Control Plan: {header.device}",
        intro=intro,
        sections=[description, protocol, impact, regulatory, checks],
        footer=DISCLAIMER,
    )

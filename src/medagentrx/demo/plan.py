# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""The demo change plan. It matches ``examples/sepsis-risk/change-plan.yaml``."""

from __future__ import annotations

import copy
from typing import Any

_BASE: dict[str, Any] = {
    "pccp_version": "1.0",
    "plan": {
        "id": "SEPSIS-RISK-PCCP",
        "revision": 3,
        "authorised": "2026-03-01",
        "device": "Sepsis risk score v2",
        "intended_use_sha256": "",
    },
    "anchor_version": "2.0.0",
    "max_updates": 12,
    "update_frequency": {"max_per": "quarter", "count": 1},
    "modifications": [
        {"id": "M1", "type": "retrain_same_architecture", "automatic": False, "scope": "global"},
        {"id": "M2", "type": "recalibrate", "automatic": False, "scope": "global"},
    ],
    "data_management": {
        "training_inclusion": {
            "all": [
                {"field": "age", "op": "ge", "value": 18},
                {"field": "site", "op": "in", "value": ["A", "B", "C"]},
                {"field": "admission_date", "op": "between", "value": ["2023-01-01", "2026-12-31"]},
            ]
        },
        "locked_test_set": {"sha256": "", "max_evaluations": 20},
        "forbid_overlap_on": ["patient_id"],
    },
    "performance": {
        "alpha_total": 0.05,
        "alpha_spending": "bonferroni",
        "operating_threshold": 0.3,
        "criteria": [
            {
                "metric": "auroc",
                "test": "non_inferiority",
                "vs": ["previous", "anchor"],
                "margin": 0.02,
            },
            {
                "metric": "sensitivity_at_threshold",
                "test": "non_inferiority",
                "vs": ["previous"],
                "margin": 0.03,
            },
            {"metric": "calibration_slope", "test": "within", "bounds": [0.8, 1.2]},
            {"metric": "calibration_intercept", "test": "within", "bounds": [-0.2, 0.2]},
            {
                "metric": "net_benefit",
                "at_thresholds": [0.1, 0.2, 0.3],
                "test": "non_inferiority",
                "vs": ["previous"],
                "margin": 0.005,
            },
        ],
        "cumulative_drift": {"metric": "auroc", "max_drop_vs_anchor": 0.02},
        "subgroups": {
            "by": ["sex", "age_band", "site"],
            "metric": "auroc",
            "max_drop": 0.03,
            "min_events": 30,
            "on_insufficient": "fail",
            "multiplicity": "none",
        },
        "power": {"min_power": 0.8},
    },
    "update_procedures": {
        "require_model_card_update": True,
        "user_communication": "Release notes to clinical users before deployment",
        "real_world_monitoring": "Monthly AUROC and calibration on live data",
    },
    "impact_assessment": {
        "benefits": "Keeps the score current as case-mix changes",
        "risks": [
            {
                "risk": "Silent performance loss in a subgroup",
                "mitigation": "Subgroup criterion tested as an intersection-union test",
            },
            {
                "risk": "Gradual drift across many small updates",
                "mitigation": "Cumulative drift guard vs anchor",
            },
        ],
    },
    "regulatory_map": {
        "fda": "PCCP final guidance, 4 Dec 2024",
        "eu": ["AI Act Art. 43(4)", "AI Act Annex IV 2(f)", "MDCG 2025-6"],
    },
}


def demo_plan(*, test_set_sha256: str, intended_use_sha256: str) -> dict[str, Any]:
    """The demo plan with the given fingerprints, as plain data."""
    plan = copy.deepcopy(_BASE)
    plan["plan"]["intended_use_sha256"] = intended_use_sha256
    plan["data_management"]["locked_test_set"]["sha256"] = test_set_sha256
    return plan

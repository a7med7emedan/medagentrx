# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Commented starter plan written by ``medagentrx init``.

Every value is inserted as JSON, which is also valid YAML, so user input is
always quoted correctly and can never change the structure of the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

PLACEHOLDER_SHA256 = "0" * 64


@dataclass(frozen=True)
class PlanAnswers:
    """Answers collected by the ``init`` wizard."""

    plan_id: str = "MY-MODEL-PCCP"
    device: str = "My clinical risk model v1"
    anchor_version: str = "1.0.0"
    authorised: str = "2026-01-01"
    intended_use_sha256: str = PLACEHOLDER_SHA256
    test_set_sha256: str = PLACEHOLDER_SHA256
    max_updates: int = 12
    max_evaluations: int = 20
    alpha_total: float = 0.05
    operating_threshold: float = 0.3
    subgroups: list[str] = field(default_factory=lambda: ["sex", "age_band", "site"])


def _q(value: object) -> str:
    return json.dumps(value, ensure_ascii=True)


def render_plan_template(answers: PlanAnswers) -> str:
    """Return the text of a commented change plan built from ``answers``."""
    intended_note = (
        "  # Replace with the SHA-256 of your intended-use statement.\n"
        if answers.intended_use_sha256 == PLACEHOLDER_SHA256
        else ""
    )
    test_note = (
        "    # Replace with the output of: medagentrx fingerprint TEST_PREDICTIONS\n"
        if answers.test_set_sha256 == PLACEHOLDER_SHA256
        else ""
    )
    subgroup_block = (
        "  subgroups:                   # every level of every column is checked\n"
        f"    by: {_q(answers.subgroups)}\n"
        "    metric: auroc\n"
        "    max_drop: 0.03\n"
        "    min_events: 30             # positives and negatives each\n"
        "    on_insufficient: fail      # or: warn\n"
        "    multiplicity: holm         # or: bonferroni\n"
        if answers.subgroups
        else ""
    )
    return f"""# Change plan for {answers.device}.
# Check it with: medagentrx validate change-plan.yaml
# Every key is described in the JSON Schema: medagentrx schema

pccp_version: "1.0"              # version of this file format

plan:
  id: {_q(answers.plan_id)}
  revision: 1                    # bump on any change to this plan
  authorised: {_q(answers.authorised)}
  device: {_q(answers.device)}
{intended_note}  intended_use_sha256: {_q(answers.intended_use_sha256)}

anchor_version: {_q(answers.anchor_version)}   # the originally authorised model
max_updates: {_q(answers.max_updates)}                 # updates allowed under this plan
update_frequency: {{max_per: quarter, count: 1}}

# FDA Description of Modifications: the only changes this plan allows.
modifications:
  - id: M1
    type: retrain_same_architecture   # or: recalibrate, fine_tune
    automatic: false                  # true lets a pipeline or agent trigger it
    scope: global                     # or: local (per site)

# FDA Modification Protocol, element 1: data management.
data_management:
  training_inclusion:                 # structured conditions, never code
    all:
      - {{field: age, op: ge, value: 18}}
  locked_test_set:
{test_note}    sha256: {_q(answers.test_set_sha256)}
    max_evaluations: {_q(answers.max_evaluations)}           # looks at the test set, ever
  forbid_overlap_on: [patient_id]

# FDA Modification Protocol, element 3: performance evaluation.
performance:
  alpha_total: {_q(answers.alpha_total)}               # error rate across all updates
  alpha_spending: bonferroni          # or: alpha_investing
  operating_threshold: {_q(answers.operating_threshold)}
  criteria:
    - {{metric: auroc, test: non_inferiority, vs: [previous, anchor], margin: 0.02}}
    - {{metric: sensitivity_at_threshold, test: non_inferiority, vs: [previous], margin: 0.03}}
    - {{metric: calibration_slope, test: within, bounds: [0.8, 1.2]}}
    - {{metric: calibration_intercept, test: within, bounds: [-0.2, 0.2]}}
  cumulative_drift:                   # bio-creep guard against the anchor
    metric: auroc
    max_drop_vs_anchor: 0.02
{subgroup_block}  power:
    min_power: 0.8

# FDA Modification Protocol, element 4: update procedures.
update_procedures:
  require_model_card_update: true
  user_communication: "Release notes to clinical users before deployment"
  real_world_monitoring: "Monthly AUROC and calibration on live data"

# FDA Impact Assessment.
impact_assessment:
  benefits: "Keeps the model current as case-mix changes"
  risks:
    - {{risk: "Silent performance loss in a subgroup", mitigation: "Subgroup criterion"}}
    - {{risk: "Gradual drift across updates", mitigation: "Cumulative drift guard"}}
"""

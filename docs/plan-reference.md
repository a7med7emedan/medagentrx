<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

<!-- This page is written by scripts/make_docs.py. Edit the code, not this file. -->

# Change plan reference

Every key of `change-plan.yaml`. Unknown keys are an error. The same definitions are in [`schema/change-plan.schema.json`](https://github.com/a7med7emedan/medagentrx/blob/main/schema/change-plan.schema.json), so editors with YAML schema support can complete and check plans as you type.

## Top level

An approved change plan (FDA PCCP, EU AI Act Art. 43(4)). Every model update is checked against it.

| Key | Type | Required | Description |
|---|---|---|---|
| `pccp_version` | `1.0` | yes | Version of this file format. |
| `plan` | PlanHeader | yes | Identity, revision and authorisation of the plan. |
| `anchor_version` | string | yes | The originally authorised model version. It never changes. |
| `ledger_signing_key_sha256` | string (pattern `^[0-9a-f]{64}$`) or null | no | Fingerprint of the Ed25519 public key that must sign every ledger head. When given, checks refuse unsigned or differently signed ledgers. |
| `anchor_predictions_sha256` | string (pattern `^[0-9a-f]{64}$`) or null | no | SHA-256 of the anchor's prediction file on the locked test set, recorded at authorisation. When given, the anchor file of every check must match it. |
| `max_updates` | integer (>= 1) | yes | Updates allowed under this plan. |
| `update_frequency` | UpdateFrequency | yes | Release frequency limit. |
| `modifications` | list of Modification | yes | FDA Description of Modifications. |
| `data_management` | DataManagement | yes | Modification Protocol, data management. |
| `performance` | Performance | yes | Modification Protocol, performance evaluation. |
| `update_procedures` | UpdateProcedures | yes | Modification Protocol, update procedures. |
| `impact_assessment` | ImpactAssessment | yes | FDA Impact Assessment. |
| `regulatory_map` | RegulatoryMap or null | no | Informative regulatory cross-reference. |

## AllCondition

True when every inner condition is true.

| Key | Type | Required | Description |
|---|---|---|---|
| `all` | list of LeafCondition or AllCondition or AnyCondition or NotCondition | yes | Conditions that must all hold. |

## AnyCondition

True when at least one inner condition is true.

| Key | Type | Required | Description |
|---|---|---|---|
| `any` | list of LeafCondition or AllCondition or AnyCondition or NotCondition | yes | Conditions of which at least one must hold. |

## CumulativeDrift

Bio-creep guard: the candidate is always compared with the anchor.

| Key | Type | Required | Description |
|---|---|---|---|
| `metric` | `auroc` | yes | Metric tracked against the anchor. |
| `max_drop_vs_anchor` | number (>= 0.0, < 1.0) | yes | Largest allowed drop below the anchor (CI lower bound). |

## DataManagement

FDA Modification Protocol, element 1: data management.

| Key | Type | Required | Description |
|---|---|---|---|
| `training_inclusion` | LeafCondition or AllCondition or AnyCondition or NotCondition | yes | Condition every row of the training manifest must meet. |
| `locked_test_set` | LockedTestSet | yes | The locked test set. |
| `forbid_overlap_on` | list of string | yes | Keys that must never be shared by training and test rows. |

## ImpactAssessment

FDA third component: benefits and risks of the planned modifications.

| Key | Type | Required | Description |
|---|---|---|---|
| `benefits` | string | yes | Expected benefits. |
| `risks` | list of Risk | yes | Risks and mitigations. |

## LeafCondition

A single comparison of one field against a literal value.

| Key | Type | Required | Description |
|---|---|---|---|
| `field` | string | yes | Column name in the training data manifest. |
| `op` | `eq` or `ne` or `lt` or `le` or `gt` or `ge` or `in` or `not_in` or `between` or `is_null` or `not_null` | yes | Comparison operator from a closed list. |
| `value` | string or integer or number or boolean or list of string or integer or number or boolean or null | no | Literal operand. A scalar for eq, ne, lt, le, gt, ge. A list for in and not_in. Two ordered values for between. Absent for is_null and not_null. Dates are written as YYYY-MM-DD strings. |

## LockedTestSet

The sequestered test set every update is evaluated on.

| Key | Type | Required | Description |
|---|---|---|---|
| `sha256` | string (pattern `^[0-9a-f]{64}$`) | yes | Canonical fingerprint of the test set, from `medagentrx fingerprint`. |
| `max_evaluations` | integer (>= 1) | yes | Looks at the locked test set allowed over the life of the plan. |

## Modification

One pre-specified modification (FDA Description of Modifications).

| Key | Type | Required | Description |
|---|---|---|---|
| `id` | string (pattern `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`) | yes | Identifier referenced by model metadata. |
| `type` | `retrain_same_architecture` or `recalibrate` or `fine_tune` | yes | Kind of change. A new architecture is never covered by a plan. |
| `automatic` | boolean | yes | True if a pipeline or agent may trigger the change without a human. |
| `scope` | `global` or `local` | yes | global: the same model for all sites. local: adapted per site. |
| `description` | string or null | no | Optional free-text description of the modification. |

## NonInferiorityCriterion

The candidate must not be worse than a comparator by more than a margin.

| Key | Type | Required | Description |
|---|---|---|---|
| `metric` | `auroc` or `sensitivity_at_threshold` or `specificity_at_threshold` or `net_benefit` | yes | Metric compared between the candidate and each comparator. |
| `test` | `non_inferiority` | yes | Paired non-inferiority test. |
| `vs` | list of `previous` or `anchor` | yes | Comparators: the previous version, the anchor, or both. |
| `margin` | number (>= 0.0, < 1.0) | yes | Non-inferiority margin on the metric. |
| `at_thresholds` | list of number (> 0.0, < 1.0) or null | no | Risk thresholds for net_benefit. Required for that metric only. |

## NotCondition

True when the inner condition is false.

| Key | Type | Required | Description |
|---|---|---|---|
| `not` | LeafCondition or AllCondition or AnyCondition or NotCondition | yes | Condition that must not hold. |

## Performance

FDA Modification Protocol, element 3: performance evaluation.

| Key | Type | Required | Description |
|---|---|---|---|
| `alpha_total` | number (> 0.0, < 1.0) | yes | Family-wise error rate across all updates under this plan. |
| `alpha_spending` | `bonferroni` or `alpha_investing` | yes | How alpha_total is spent across updates. |
| `operating_threshold` | number (> 0.0, < 1.0) | yes | Risk threshold at which sensitivity and specificity are assessed. |
| `criteria` | list of NonInferiorityCriterion or WithinCriterion | yes | Acceptance criteria. |
| `cumulative_drift` | CumulativeDrift | yes | Bio-creep guard against the anchor. |
| `subgroups` | Subgroups or null | no | Subgroup criterion. |
| `power` | Power or null | no | Power requirement. |

## PlanHeader

Identity of the authorised plan.

| Key | Type | Required | Description |
|---|---|---|---|
| `id` | string (pattern `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`) | yes | Stable identifier of the plan. |
| `revision` | integer (>= 1) | yes | Plan revision. Any change to the plan itself must bump this. |
| `authorised` | string | yes | Date the plan was authorised, as YYYY-MM-DD. |
| `device` | string | yes | Name of the device or model the plan governs. |
| `intended_use_sha256` | string (pattern `^[0-9a-f]{64}$`) | yes | SHA-256 of the intended-use statement. A change means a new intended use. |

## Power

Power requirement for the locked test set.

| Key | Type | Required | Description |
|---|---|---|---|
| `min_power` | number (> 0.0, < 1.0) | yes | Warn when power to detect the margin is lower. |

## RegulatoryMap

Informative cross-reference, rendered in the plan document.

| Key | Type | Required | Description |
|---|---|---|---|
| `fda` | string or null | no | FDA reference. |
| `eu` | list of string | no | EU references. |

## Risk

One risk of the planned modifications and its mitigation.

| Key | Type | Required | Description |
|---|---|---|---|
| `risk` | string | yes | The risk. |
| `mitigation` | string | yes | How the plan mitigates it. |

## Subgroups

Subgroup criterion applied to every level of every listed column.

| Key | Type | Required | Description |
|---|---|---|---|
| `by` | list of string | yes | Subgroup columns in the prediction files. |
| `metric` | `auroc` | yes | Metric compared within each subgroup. |
| `max_drop` | number (>= 0.0, < 1.0) | yes | Largest allowed drop in any subgroup. |
| `min_events` | integer (>= 1) | yes | Positives and negatives each needed, else insufficient evidence. |
| `on_insufficient` | `fail` or `warn` | yes | What an insufficient-evidence subgroup does to the verdict. |
| `multiplicity` | `none` or `holm` or `bonferroni` | yes | Correction across subgroups. 'none' is the intersection-union test: the update passes only if every subgroup is non-inferior, so each is tested at the full level. 'holm' and 'bonferroni' are stricter. |

## UpdateFrequency

How often updates may be released.

| Key | Type | Required | Description |
|---|---|---|---|
| `max_per` | `month` or `quarter` or `year` | yes | Calendar period. |
| `count` | integer (>= 1) | yes | Maximum number of updates in each period. |

## UpdateProcedures

FDA Modification Protocol, element 4: update procedures.

| Key | Type | Required | Description |
|---|---|---|---|
| `require_model_card_update` | boolean | yes | True if each release must update the model card. |
| `user_communication` | string | yes | How users are told about an update. |
| `real_world_monitoring` | string | yes | How performance is monitored after release. |

## WithinCriterion

The candidate's metric must lie inside fixed bounds.

| Key | Type | Required | Description |
|---|---|---|---|
| `metric` | `calibration_slope` or `calibration_intercept` | yes | Calibration measure of the candidate on the locked test set. |
| `test` | `within` | yes | Bounds test on the candidate alone. |
| `bounds` | list of any | yes | Inclusive lower and upper bound. |

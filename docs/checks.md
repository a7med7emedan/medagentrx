<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

<!-- This page is written by scripts/make_docs.py. Edit the code, not this file. -->

# Checks catalogue

Every check has an identifier, a family, what a failure does to the verdict, and a regulatory cross-reference. A failure marked OUTSIDE_PLAN makes the update outside the plan. Any other failure gives FAILED. Warnings never change the verdict.

| Check | Family | What it checks | If it fails | Cross-reference |
|---|---|---|---|---|
| PLAN-001 | PLAN | Plan is valid and unchanged since the ledger began | OUTSIDE PLAN | A change to a PCCP needs a new submission |
| PLAN-002 | PLAN | Modification is listed in the plan | OUTSIDE PLAN | FDA Description of Modifications |
| PLAN-003 | PLAN | Intended use is unchanged | OUTSIDE PLAN | Focused and bounded principle; AI Act substantial modification |
| PLAN-004 | PLAN | Update count and frequency are within the plan | OUTSIDE PLAN | FDA Description of Modifications, frequency |
| DATA-001 | DATA | Locked test set is unchanged | OUTSIDE PLAN | Modification Protocol, data management |
| DATA-002 | DATA | No overlap between training and test data | FAILED | Data management; test data sequestration |
| DATA-003 | DATA | Every training row meets the inclusion criteria | OUTSIDE PLAN | Data management; AI Act Art. 10 |
| DATA-004 | DATA | Test-set evaluation budget is not exceeded | OUTSIDE PLAN | Test data sequestration; adaptive overfitting (Dwork et al. 2015) |
| DATA-005 | DATA | Population shift between training and test data | WARNING | Evidence-based principle |
| DATA-006 | DATA | Prediction files are the ones the models produced | OUTSIDE PLAN | Traceability; Modification Protocol, update procedures |
| PERF-001 | PERF | AUROC is non-inferior (paired DeLong) | FAILED | Performance evaluation protocol |
| PERF-002 | PERF | Sensitivity and specificity at the operating threshold are non-inferior | FAILED | Performance evaluation protocol |
| PERF-003 | PERF | Calibration slope and intercept are within bounds | FAILED | AI Act Art. 15 accuracy |
| PERF-004 | PERF | Net benefit at clinical thresholds is non-inferior (paired bootstrap) | FAILED | Evidence-based principle; clinical utility |
| PERF-005 | PERF | No subgroup loses more than the allowed AUROC | FAILED | Transparency principle; AI Act Art. 10 bias |
| PERF-006 | PERF | Test set has power to detect the margin | WARNING | Evidence-based principle |
| LIFE-001 | LIFE | Cumulative drift against the anchor is within budget (bio-creep guard) | FAILED | Feng et al. 2021, Biometrics |
| LIFE-002 | LIFE | Alpha budget is not exhausted | OUTSIDE PLAN | Error control across the lifecycle |
| DOC-001 | DOC | Model card section for this version can be completed | FAILED | Update procedures; labelling |

## Details

**PLAN-001: Plan is valid and unchanged since the ledger began.** The plan validated on loading; here it must match the plan the ledger started with.

**PLAN-002: Modification is listed in the plan.** The candidate's modification_id must name a plan modification.

**PLAN-003: Intended use is unchanged.** The candidate's intended-use hash must equal the plan's.

**PLAN-004: Update count and frequency are within the plan.** Released updates so far must leave room for one more, overall and this period.

**DATA-001: Locked test set is unchanged.** Fingerprint must match the plan, and all versions must share rows and labels.

**DATA-002: No overlap between training and test data.** No value of a ``forbid_overlap_on`` key may occur in both training and test data.

**DATA-003: Every training row meets the inclusion criteria.** Every manifest row must satisfy ``training_inclusion``.

**DATA-004: Test-set evaluation budget is not exceeded.** This look must fit inside ``max_evaluations``.

**DATA-005: Population shift between training and test data.** Warn when a shared feature has |SMD| above 0.1 between training and test data.

**DATA-006: Prediction files are the ones the models produced.** Bind each prediction file to its model.

**PERF-001: AUROC is non-inferior (paired DeLong).** Paired DeLong non-inferiority against each comparator in the plan.

**PERF-002: Sensitivity and specificity at the operating threshold are non-inferior.** Tango paired score intervals at the operating threshold.

**PERF-003: Calibration slope and intercept are within bounds.** Point estimates of slope and intercept must lie inside the plan's bounds.

**PERF-004: Net benefit at clinical thresholds is non-inferior (paired bootstrap).** Paired bootstrap percentile interval of the net benefit difference at each threshold.

**PERF-005: No subgroup loses more than the allowed AUROC.** Per-subgroup non-inferiority against the previous version; every subgroup must pass.

**PERF-006: Test set has power to detect the margin.** Analytic power of the AUROC test against the previous version.

**LIFE-001: Cumulative drift against the anchor is within budget (bio-creep guard).** The lower bound of AUC_candidate - AUC_anchor must stay at or above -max_drop.

**LIFE-002: Alpha budget is not exhausted.** Some alpha must remain for this evaluation.

**DOC-001: Model card section for this version can be completed.** When the plan requires a model card update, every number it needs must exist.

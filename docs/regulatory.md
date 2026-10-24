<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Regulatory mapping (informative)

This page shows where MedAgentRx touches each regulatory element. It is informative only. Whether a plan meets a regulation is for the manufacturer and the reviewer to decide.

## FDA PCCP (final guidance issued 4 December 2024, reissued 18 August 2025)

| PCCP component | Plan section | Checks |
|---|---|---|
| Description of Modifications | `modifications`, `max_updates`, `update_frequency` | PLAN-002, PLAN-004 |
| Modification Protocol: data management | `data_management` | DATA-001 to DATA-006 |
| Modification Protocol: re-training | `modifications[].type` | PLAN-002, recorded architecture fingerprint |
| Modification Protocol: performance evaluation | `performance` | PERF-001 to PERF-006, LIFE-001, LIFE-002 |
| Modification Protocol: update procedures | `update_procedures`, `deployment_qc` | DOC-001; card and release records in the decision ledger; LIVE-001 to LIVE-004 |
| Impact Assessment | `impact_assessment` | rendered in the PCCP document |

FDA, Health Canada and MHRA published five guiding principles for PCCPs: focused and bounded, risk-based, evidence-based, transparent, and total product lifecycle. The plan's closed list of modifications and fixed intended use keep it focused and bounded. Pre-specified criteria and the locked test set make it evidence-based. The ledger and reports make it transparent. The bio-creep guard and alpha spending cover the lifecycle.

The guidance places "real-world monitoring plans as applicable" within the update procedures, and states that FDA "anticipates that manufacturers will monitor their device's safety (e.g., adverse events) and effectiveness (e.g., performance) over time". [Deployment QC](qc.md) supplies one such activity: it checks that the deployed system still reproduces the authorised version's outputs on locked control records. It does not measure clinical performance on new patients, which needs outcome data and remains part of the manufacturer's monitoring plan.

## EU AI Act and MDR

| Requirement | How it is reflected |
|---|---|
| Article 43(4): pre-determined changes are not a substantial modification | The plan file is the record of pre-determined changes; OUTSIDE_PLAN marks anything else |
| Annex IV point 2(f): description of pre-determined changes in the technical documentation | `medagentrx render-plan` writes that description from the same file the gate runs |
| Article 10: data governance | DATA-002 and DATA-003 |
| Article 15(1): accuracy, robustness and cybersecurity, performing "consistently in those respects throughout their lifecycle" | PERF-001 to PERF-004 for each update; LIVE-003 and LIVE-004 for the deployed system between updates |
| Article 72: post-market monitoring by providers, which must "actively and systematically collect, document and analyse relevant data" on performance | Deployment QC runs and their ledger entries are documented, systematic evidence that the deployed system is unchanged; they feed the provider's monitoring plan and do not replace it |
| MDCG 2025-6 | Predetermined changes are not substantial under the AI Act; MDR significant change is still assessed separately and is outside this tool |
| MDR (EU) 2017/745 Article 83: the manufacturer's post-market surveillance system, gathering data on "quality, performance and safety of a device throughout its entire lifetime" | Deployment QC records are one input to that system. Surveillance of clinical performance and safety remains the manufacturer's |

## What MedAgentRx does not do

- It does not decide whether a change is significant under the MDR.
- It does not replace a quality management system, design controls or clinical evaluation.
- Its output is not itself a regulatory submission.
- Deployment QC does not measure clinical performance on new patients. It checks that the deployed software still behaves as the authorised version did.

Quotations were checked against the published texts: Regulation (EU) 2024/1689 (Articles 15, 43 and 72), Regulation (EU) 2017/745 (Article 83), and the FDA guidance "Marketing Submission Recommendations for a Predetermined Change Control Plan for Artificial Intelligence-Enabled Device Software Functions" as reissued on 18 August 2025.

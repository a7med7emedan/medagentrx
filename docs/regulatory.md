<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Regulatory mapping (informative)

This page shows where MedAgentRx touches each regulatory element. It is informative only. Whether a plan meets a regulation is for the manufacturer and the reviewer to decide.

## FDA PCCP (final guidance, 4 December 2024)

| PCCP component | Plan section | Checks |
|---|---|---|
| Description of Modifications | `modifications`, `max_updates`, `update_frequency` | PLAN-002, PLAN-004 |
| Modification Protocol: data management | `data_management` | DATA-001 to DATA-005 |
| Modification Protocol: re-training | `modifications[].type` | PLAN-002, recorded architecture fingerprint |
| Modification Protocol: performance evaluation | `performance` | PERF-001 to PERF-006, LIFE-001, LIFE-002 |
| Modification Protocol: update procedures | `update_procedures` | DOC-001, decision ledger |
| Impact Assessment | `impact_assessment` | rendered in the PCCP document |

FDA, Health Canada and MHRA published five guiding principles for PCCPs: focused and bounded, risk-based, evidence-based, transparent, and total product lifecycle. The plan's closed list of modifications and fixed intended use keep it focused and bounded. Pre-specified criteria and the locked test set make it evidence-based. The ledger and reports make it transparent. The bio-creep guard and alpha spending cover the lifecycle.

## EU AI Act and MDR

| Requirement | How it is reflected |
|---|---|
| Article 43(4): pre-determined changes are not a substantial modification | The plan file is the record of pre-determined changes; OUTSIDE_PLAN marks anything else |
| Annex IV point 2(f): description of pre-determined changes in the technical documentation | `medagentrx render-plan` writes that description from the same file the gate runs |
| Article 10: data governance | DATA-002 and DATA-003 |
| Article 15: accuracy | PERF-001 to PERF-004 |
| MDCG 2025-6 | Predetermined changes are not substantial under the AI Act; MDR significant change is still assessed separately and is outside this tool |

## What MedAgentRx does not do

- It does not decide whether a change is significant under the MDR.
- It does not replace a quality management system, design controls or clinical evaluation.
- Its output is not itself a regulatory submission.

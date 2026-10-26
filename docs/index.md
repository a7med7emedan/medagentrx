<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# MedAgentRx

**The prescription for self-improving medical AI.** Every model update, by an engineer, a pipeline or an AI agent, is checked against its approved change plan (FDA PCCP, EU AI Act Art. 43(4)).

![How MedAgentRx decides: a candidate update and the approved change plan enter the gate, which asks whether the update is what was approved, whether it is inside the plan and whether it is good enough; a hash-chained ledger records every attempt; the result is ACCEPTED, FAILED or OUTSIDE_PLAN with reports.](assets/how-it-works.svg)

Clinical risk models are increasingly retrained by scheduled pipelines and by AI agents. MedAgentRx lets them change a model only in the ways the approved change plan allows, and tests every change with the statistics a regulatory reviewer expects.

## Background: change control plans

A cleared or certified medical AI model normally cannot be retrained without a new regulatory review. Regulators now offer an alternative: the manufacturer describes in advance which changes it will make and how it will validate them.

- In the United States this is the **Predetermined Change Control Plan (PCCP)**. FDA final guidance for AI-enabled device software functions was issued on 4 December 2024. It has three parts: Description of Modifications, Modification Protocol and Impact Assessment.
- In the European Union, **AI Act Article 43(4)** says changes that were pre-determined at the initial conformity assessment, and recorded in the technical documentation, are not a substantial modification. MDCG 2025-6 confirms this, while a significant change under the MDR is still assessed separately.

These plans are usually documents, checked by hand at each update. MedAgentRx makes the plan executable. You write it once as `change-plan.yaml`, and every update is tested against it.

## Verdicts

| Verdict | Meaning | Exit code |
|---|---|---|
| **ACCEPTED** | Inside the plan, and every criterion met. | 0 |
| **FAILED** | Inside the plan, but a criterion was not met. Do not release. | 1 |
| **OUTSIDE_PLAN** | Not covered by the plan. A new submission is needed. | 2 |

Input and usage errors exit with 3. Warnings never change the verdict. They always appear in the report.

## What it checks

Nineteen checks in five families run on every update, and four LIVE checks judge each [deployment QC](qc.md) run of the live system. The [checks catalogue](checks.md) lists them all.

- **PLAN**: the plan is unchanged, the modification is listed, the intended use is the same, and the update fits the plan's count and frequency.
- **DATA**: the locked test set is unchanged, training and test data do not overlap, training data meets the inclusion criteria, the test set has looks left, and each prediction file is the one its model produced.
- **PERF**: AUROC, sensitivity and specificity, calibration, net benefit and every subgroup meet the plan's criteria, and the test set has power for the margin.
- **LIFE**: the model has not drifted from the authorised version (bio-creep), and alpha remains.
- **DOC**: the model card is kept up to date across versions.

Every evaluation, failures included, is written to a hash-chained [decision ledger](ledger.md). Looks at the test set and alpha spent are read back from it, so nobody can keep trying candidates until one passes by chance.

## Where next

- [Quickstart](quickstart.md): run the synthetic demo, then your own plan.
- [Tutorial](tutorial.md): take one update from plan to evidence, step by step.
- [For agents and AutoML](agents.md): the guard that keeps an agent inside the plan.
- [For reviewers](reviewers.md): verify an evidence bundle, read a report and verify a ledger.
- [Glossary](glossary.md): the terms these pages use, in plain words.

!!! note "Disclaimer"
    MedAgentRx supports a quality management system. It is not legal or regulatory advice, does not replace your QMS or regulatory strategy, and its output is not itself a regulatory submission.

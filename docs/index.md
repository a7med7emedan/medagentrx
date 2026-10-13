<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# MedAgentRx

**The prescription for self-improving medical AI.** Every model update, by an engineer, a pipeline or an AI agent, is checked against its approved change plan (FDA PCCP, EU AI Act Art. 43(4)).

AI agents and automated pipelines now retrain clinical models on their own. MedAgentRx lets them change a model only as the approved plan prescribes. The regulatory and statistical rigour sits behind that boundary.

## A change plan in five minutes

A cleared or certified medical AI model normally cannot be retrained without a new regulatory review. Regulators now accept a way around that: describe in advance which changes you will make and how you will validate them.

- In the United States this is the **Predetermined Change Control Plan (PCCP)**. FDA final guidance for AI-enabled device software functions was issued on 4 December 2024. It has three parts: Description of Modifications, Modification Protocol and Impact Assessment.
- In the European Union, **AI Act Article 43(4)** says changes that were pre-determined at the initial conformity assessment, and recorded in the technical documentation, are not a substantial modification. MDCG 2025-6 confirms this, while a significant change under the MDR is still assessed separately.

Today these plans live in documents and are checked by hand. MedAgentRx makes the plan executable. You write it once as `change-plan.yaml`, and every update is checked against it.

## Three verdicts

| Verdict | Meaning | Exit code |
|---|---|---|
| **ACCEPTED** | Inside the plan, and every criterion met. | 0 |
| **FAILED** | Inside the plan, but a criterion was not met. Do not release. | 1 |
| **OUTSIDE_PLAN** | Not covered by the plan. A new submission is needed. | 2 |

Input and usage errors exit with 3. Warnings never change the verdict, but they always appear in the report.

## What it checks

Eighteen checks in five families run on every update. The [checks catalogue](checks.md) lists them all.

- **PLAN**: the plan is unchanged, the modification is listed, the intended use is the same, and the update fits the plan's count and frequency.
- **DATA**: the locked test set is unchanged, training and test data do not overlap, training data meets the inclusion criteria, and the test set has looks left.
- **PERF**: AUROC, sensitivity and specificity, calibration, net benefit and every subgroup meet the plan's criteria, and the test set has power for the margin.
- **LIFE**: the model has not drifted from the authorised version (bio-creep), and alpha remains.
- **DOC**: the model card can be updated.

Every evaluation, including failed ones, is written to a hash-chained [decision ledger](ledger.md). The looks at the test set and the alpha it spends are therefore counted, so no one, person or agent, can keep trying until a candidate passes by chance.

## Where next

- [Quickstart](quickstart.md): run the synthetic demo, then your own plan.
- [For agents and AutoML](agents.md): the guard that keeps an agent inside the plan.
- [For reviewers](reviewers.md): read a report and verify a ledger.

!!! note "Disclaimer"
    MedAgentRx supports a quality management system. It is not legal or regulatory advice, does not replace your QMS or regulatory strategy, and its output is not itself a regulatory submission.

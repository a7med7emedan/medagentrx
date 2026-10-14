<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

<p align="center">
  <img src="https://a7med7emedan.github.io/medagentrx/assets/logo.svg" alt="MedAgentRx logo: a prescription sign whose upright stroke is a gate post and whose crossing stroke is a confidence-interval whisker" width="360">
</p>

<p align="center"><strong>The prescription for self-improving medical AI.</strong><br>
Every model update, by an engineer, a pipeline or an AI agent, is checked against its approved change plan (FDA PCCP, EU AI Act Art. 43(4)).</p>

<p align="center">
  <a href="https://github.com/a7med7emedan/medagentrx/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/a7med7emedan/medagentrx/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/medagentrx/"><img alt="PyPI" src="https://img.shields.io/pypi/v/medagentrx?color=0F766E"></a>
  <a href="https://a7med7emedan.github.io/medagentrx/"><img alt="Documentation" src="https://img.shields.io/badge/docs-online-0F766E"></a>
  <a href="https://github.com/a7med7emedan/medagentrx/blob/main/pyproject.toml"><img alt="Python 3.11 to 3.13" src="https://img.shields.io/badge/python-3.11%20to%203.13-0F766E"></a>
  <a href="https://github.com/a7med7emedan/medagentrx/blob/main/LICENSE"><img alt="Licence: Apache-2.0" src="https://img.shields.io/badge/licence-Apache--2.0-0F766E"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/a7med7emedan/medagentrx"><img alt="OpenSSF Scorecard" src="https://api.scorecard.dev/projects/github.com/a7med7emedan/medagentrx/badge"></a>
</p>

Clinical risk models are increasingly retrained by scheduled pipelines and by AI agents. Regulators allow this only for changes agreed in advance, in a Predetermined Change Control Plan in the US or under Article 43(4) of the EU AI Act. MedAgentRx turns that plan into a test that runs on every update.

The plan is a single YAML file. Each candidate update is evaluated against it and receives one verdict: **ACCEPTED**, **FAILED** or **OUTSIDE_PLAN**. Every evaluation, including every failure, is appended to a hash-chained ledger, and the plan's limits are read back from it. Each attempt uses up part of the plan's budget of looks at the locked test set. A model therefore cannot be selected simply because it passed once among many tries.

Each verdict rests on established methods. AUROC is compared with paired DeLong tests, cross-checked against R pROC. Calibration is judged by slope and intercept, and clinical value by net benefit at the plan's decision thresholds. Every subgroup must be non-inferior on its own. Alpha is spent across the life of the plan, and each update is also compared with the originally authorised version, which catches slow drift. [Methods](https://a7med7emedan.github.io/medagentrx/methods/) gives the formulas and references.

<p align="center"><img src="https://a7med7emedan.github.io/medagentrx/assets/how-it-works.svg" alt="How MedAgentRx decides: a candidate update from an engineer, a pipeline or an AI agent, together with the approved change plan, enters the gate. The gate asks whether the update is what was approved, whether it is inside the plan, and whether it is good enough. A hash-chained ledger records every attempt and supplies the remaining budgets. The result is ACCEPTED, FAILED or OUTSIDE_PLAN with an exit code, and reports for review." width="900"></p>

## What it checks

| Family | Checks | A failure means |
|---|---|---|
| PLAN | The plan is unchanged, the modification is listed, the intended use is the same, the update fits the plan's count and frequency | OUTSIDE_PLAN |
| DATA | Locked test set unchanged, no training and test overlap, training data in scope, test-set looks left, population shift, prediction files bound to their models | OUTSIDE_PLAN, FAILED or a warning |
| PERF | AUROC, sensitivity and specificity, calibration, net benefit and every subgroup meet the plan; power for the margin | FAILED or a warning |
| LIFE | No bio-creep against the authorised version; alpha left | FAILED or OUTSIDE_PLAN |
| DOC | The model card is kept up to date across versions | FAILED |

The [checks catalogue](https://a7med7emedan.github.io/medagentrx/checks/) lists all 19 checks with their regulatory cross-references.

## Quick start

```bash
pip install medagentrx
medagentrx demo
```

The demo runs ten scenarios on a synthetic cohort, with no real patient data. Each scenario plants one defect, or none, and must produce exactly its expected verdict. To check your own update:

```bash
medagentrx init                                   # write a commented change-plan.yaml
medagentrx sample-size change-plan.yaml --auroc 0.80 --prevalence 0.12
medagentrx fingerprint test-predictions.parquet   # fingerprint the locked test set
medagentrx check change-plan.yaml \
  --candidate candidate.parquet --previous previous.parquet --anchor anchor.parquet \
  --manifest train_manifest.parquet --model-meta model.yaml \
  --ledger ledger.jsonl --out report/
```

A typical result, for an update that improved overall but lost accuracy at one hospital site:

```text
verdict: FAILED
  FAIL PERF-005: Subgroup AUROC drop beyond the limit: site=C (-0.060)
report: report/report.html
report: report/report.json
report: report/summary.md
report: report/junit.xml
ledger: entry 0 3dbcd0bb2b0b
```

The exit code is the verdict: 0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN, 3 input error. `report/` holds a self-contained HTML report, JSON, a Markdown summary and JUnit XML. MedAgentRx reads prediction files only and never loads a model binary.

## The plan

```yaml
modifications:                 # FDA Description of Modifications
  - {id: M1, type: retrain_same_architecture, automatic: false, scope: global}
data_management:
  training_inclusion:
    all:
      - {field: age, op: ge, value: 18}
      - {field: site, op: in, value: [A, B, C]}
  locked_test_set: {sha256: "e9a46f9b...", max_evaluations: 20}
  forbid_overlap_on: [patient_id]
performance:
  alpha_total: 0.05
  alpha_spending: bonferroni
  criteria:
    - {metric: auroc, test: non_inferiority, vs: [previous, anchor], margin: 0.02}
    - {metric: calibration_slope, test: within, bounds: [0.8, 1.2]}
  cumulative_drift: {metric: auroc, max_drop_vs_anchor: 0.02}
  subgroups: {by: [sex, age_band, site], metric: auroc, max_drop: 0.03, min_events: 30,
              on_insufficient: fail, multiplicity: none}
```

The full example is [`examples/sepsis-risk/change-plan.yaml`](https://github.com/a7med7emedan/medagentrx/blob/main/examples/sepsis-risk/change-plan.yaml). `medagentrx render-plan` turns the same file into the PCCP document, with the FDA components and the EU AI Act cross-reference, so the document and the gate cannot drift apart.

## Automated retraining and agents

```python
from medagentrx.guard import Guard

guard = Guard("change-plan.yaml", "ledger.jsonl", mode="thresholdout", previous="previous.parquet")
decision = guard.submit("candidate.parquet", "model.yaml", manifest="train_manifest.parquet")
print(decision.allowed, decision.reason, decision.looks_remaining)
```

An agent may try only the modifications the plan marks as automatic. Each try spends one look at the locked test set. In the default thresholdout mode the agent learns only whether the candidate passes, with random noise added so that repeated tries reveal little about the test set. If the agent also supplies predictions on its own validation data, the guard follows Thresholdout (Dwork et al. 2015) and answers from those whenever they agree with the test set. See [For agents and AutoML](https://a7med7emedan.github.io/medagentrx/agents/).

## Continuous integration

GitHub Actions:

```yaml
- uses: a7med7emedan/medagentrx@v0.1.1
  with:
    plan: change-plan.yaml
    candidate: predictions/candidate.parquet
    previous: predictions/previous.parquet
    anchor: predictions/anchor.parquet
    manifest: data/train_manifest.parquet
    model-meta: model.yaml
    ledger: governance/ledger.jsonl
```

GitLab CI/CD:

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/medagentrx/medagentrx@0.1.1
    inputs:
      image: <registry>/medagentrx@sha256:<digest>
      plan: change-plan.yaml
      # same inputs as above
```

There is also a `medagentrx-validate` pre-commit hook. See the [CI guides](https://a7med7emedan.github.io/medagentrx/ci/).

## Verdicts

| Verdict | Meaning |
|---|---|
| **ACCEPTED** | Inside the plan, and every criterion met. |
| **FAILED** | Inside the plan, but a criterion was not met. Do not release. |
| **OUTSIDE_PLAN** | Not covered by the plan. It needs a new submission. |

Warnings never change the verdict. They always appear in the report.

## Validation

<p align="center"><img src="https://a7med7emedan.github.io/medagentrx/assets/validation.svg" alt="Simulation grid across prevalence 5 to 30 percent and 500 to 20,000 rows: type I error between 0.047 and 0.054, power rising with size, bootstrap coverage between 0.933 and 0.950" width="760"></p>

The simulation grid spans prevalence 5 to 30 percent and test sets of 500 to 20,000 rows, with 20,000 replicates per cell for type I error and 10,000 for coverage. At a nominal one-sided 5 percent, the non-inferiority test rejects a true boundary null 4.7 to 5.4 percent of the time. Nominal 95 percent bootstrap intervals cover 93.3 to 95.0 percent. DeLong results match R pROC to 1e-8 on AUC and 1e-6 on standard error and z. See [validation results](https://a7med7emedan.github.io/medagentrx/validation/) and [methods](https://a7med7emedan.github.io/medagentrx/methods/).

## Security

Inputs are data only: no unpickling, no `eval`, no user code. Plans are parsed with a hardened safe YAML loader and strict schemas. Reports are self-contained and load nothing. The container runs as a non-root user with a read-only file system, and has no HIGH or CRITICAL Trivy findings. Report vulnerabilities privately as described in [SECURITY.md](https://github.com/a7med7emedan/medagentrx/blob/main/SECURITY.md).

## Citing

If you use MedAgentRx in research, please cite it using [`CITATION.cff`](https://github.com/a7med7emedan/medagentrx/blob/main/CITATION.cff).

## Disclaimer

MedAgentRx supports a quality management system. It is not legal or regulatory advice, does not replace your QMS or regulatory strategy, and its output is not itself a regulatory submission.

## Author

Ahmed Hemedan. Licensed under [Apache-2.0](https://github.com/a7med7emedan/medagentrx/blob/main/LICENSE).

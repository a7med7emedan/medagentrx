<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Quickstart

## One minute: the synthetic demo

```bash
uvx medagentrx demo
```

The demo builds a synthetic sepsis cohort of 20,000 test rows (no real patient data) and runs ten planted scenarios. Each model version is recalibrated on a separate development sample, never on the locked test set, so the test set shows the small calibration error a real update carries. Each must give exactly its expected verdict:

| Scenario | Planted property | Verdict | Check |
|---|---|---|---|
| good-update | Better AUROC, calibrated, no subgroup harm | ACCEPTED | none |
| subgroup-harm | Overall better, one site drops 0.06 | FAILED | PERF-005 |
| miscalibrated | Same AUROC, slope 0.6 | FAILED | PERF-003 |
| leaky-training | 300 test patients in the training data | FAILED | DATA-002 |
| test-set-tampered | Test labels edited | OUTSIDE_PLAN | DATA-001 |
| new-architecture | Modification not in the plan | OUTSIDE_PLAN | PLAN-002 |
| out-of-scope-data | Paediatric rows in training | OUTSIDE_PLAN | DATA-003 |
| bio-creep | Five updates each 0.008 AUROC worse | FAILED at the fifth | LIFE-001 |
| peeking-agent | An agent submits 25 candidates on a budget of 20 | OUTSIDE_PLAN at the 21st | DATA-004 |
| underpowered | Test set too small for the margin | ACCEPTED with a warning | PERF-006 |

Reports for every step are written under `medagentrx-demo/`. Open any `report.html` in a browser; it works offline.

## Ten minutes: your own plan

1. **Write the plan.** `medagentrx init` asks a few questions and writes a commented `change-plan.yaml`. Every key is described in the [change plan reference](plan-reference.md).
2. **Check it.** `medagentrx validate change-plan.yaml`.
3. **Size the test set before you lock it.** `medagentrx sample-size change-plan.yaml --auroc 0.80 --prevalence 0.12` gives the rows needed for the plan's power. A test set that is too small fails good updates.
4. **Fingerprint the locked test set.** `medagentrx fingerprint test-predictions.parquet`, and paste the result into `locked_test_set.sha256`.
5. **Export predictions.** For each model version, write a Parquet or CSV file with `row_id`, `y_true`, `y_score` and the subgroup columns the plan names. The candidate file also carries the keys in `forbid_overlap_on`, such as `patient_id`. Model binaries are never loaded.
6. **Describe the candidate** in `model.yaml`: version, previous version, modification id, and the SHA-256 of its architecture, intended-use statement, training manifest and prediction file. The prediction hash binds the file being checked to the model that produced it (DATA-006).
7. **Check the update.**

```bash
medagentrx check change-plan.yaml \
  --candidate candidate.parquet --previous previous.parquet --anchor anchor.parquet \
  --manifest train_manifest.parquet --model-meta model.yaml \
  --ledger ledger.jsonl --out report/
```

The exit code is the verdict. `report/` holds `report.html`, `report.json`, `summary.md` and `junit.xml`. Keep `ledger.jsonl` and `ledger.jsonl.head` between runs, for example in version control.

The `examples/sepsis-risk` folder holds a complete example to copy from.

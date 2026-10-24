<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Deployment QC

A model's weights can stay the same while its behaviour changes. A new library version, inference runtime, hardware type or preprocessing step can each move the scores a deployed model gives. Nothing in the change plan would record such a change, so it is an update nobody declared.

A clinical laboratory does not trust an analyser because its serial number is unchanged. It runs a control sample with a known answer on a schedule, and stops when the result drifts. Deployment QC does the same for the live model.

## How it works

1. You lock a small control set of raw input records, taken before any preprocessing, so the whole live stack is exercised. The records stay with you. The plan stores only their fingerprints.
2. For each released version, the plan records the expected scores of that version on the control set.
3. On a schedule, the live system scores the control set. MedAgentRx reads the resulting score file only. It never runs the model.
4. Each run is compared with the expected scores, judged with laboratory multirule QC, and written to the decision ledger. The run history comes from the ledger.

A run gives one verdict:

| Verdict | Exit code | Meaning |
|---|---|---|
| **IN_CONTROL** | 0 | The live system reproduced the released version's scores. Warnings may appear. |
| **OUTSIDE_PLAN** | 2 | The live system no longer behaves like the released version. Investigate before relying on it. |

Input errors, such as a malformed score file, exit with 3, as everywhere else.

## The four LIVE checks

| Check | What it enforces |
|---|---|
| LIVE-001 | The version running live is the released one: the latest `release` record in the ledger, or the plan's anchor version when none exists. |
| LIVE-002 | The live and expected score files cover exactly the locked control ids, the expected file is the one the plan records for this version, and the raw control inputs match when given. |
| LIVE-003 | No control record moves further from its expected score than the plan's tolerance. |
| LIVE-004 | The run bias, the mean of live minus expected score, passes the multirule QC rules over the version's run history. |

Every LIVE failure breaks the plan. If LIVE-001 or LIVE-002 fails, LIVE-003 and LIVE-004 are not assessed, because the run is not bound to the released version and control set.

### Multirule QC

LIVE-004 applies the rules of Westgard et al. (1981) to the run bias, in SD units from the target mean. There is one control material, so the rules look across successive runs.

| Rule | Fires when | Effect |
|---|---|---|
| 1_2s | the latest run is more than 2 SD from the mean | warning |
| 1_3s | the latest run is more than 3 SD from the mean | rejection |
| 2_2s | the latest two runs are more than 2 SD from the mean on the same side | rejection |
| R_4s | the latest two runs lie more than 2 SD on opposite sides of the mean | rejection |
| 10_x | the latest ten runs lie on the same side of the mean | rejection |

When the plan gives `sd`, the target bias is zero, because the expected scores are the truth. When `sd` is null, the mean and SD are estimated from the first `baseline_runs` in-control runs of each version, as a laboratory sets its own limits on its own analyser. Until the baseline is complete, only LIVE-001 to LIVE-003 apply, and the report says so. Rejected runs never join the baseline or later rule windows.

A deterministic stack reproduces its scores exactly, so its estimated SD is zero. The SD therefore has a floor: the tolerance divided by three times the square root of the number of control records. That is the SD the bias would have if every record varied with an SD of a third of the tolerance, the most noise the plan accepts.

## Set it up

1. Choose 100 to 500 raw records that cover the case mix. They must never be used for training or testing. Save them with a `row_id` column.
2. Score them with the authorised version, exactly as live requests go, and save the scores with `row_id` and `y_score`.
3. Print the plan block, checking that the control ids are disjoint from the locked test set and the training data:

```bash
medagentrx qc init --control-inputs control_inputs.parquet \
  --scores expected-2.0.0.parquet --version 2.0.0 \
  --test-set test-predictions.parquet --manifest train_manifest.parquet
```

4. Paste the printed `deployment_qc` block into `change-plan.yaml`. Adding it changes the plan, so it needs a new plan revision.

```yaml
deployment_qc:
  control_inputs_sha256: "<64 hex>"
  control_ids_fingerprint: "<64 hex>"
  expected_scores: {"2.0.0": "<sha256 of the expected score file>"}
  tolerance: {absolute: 1.0e-06}
  rules: [1_2s, 1_3s, 2_2s, R_4s, 10_x]
  sd: null            # or a number
  baseline_runs: 20   # used when sd is null
  schedule: "daily"   # documentation only
```

## Run it on a schedule

MedAgentRx does not schedule anything. A scheduler of your choice scores the control set with the production service and runs:

```bash
medagentrx qc run change-plan.yaml --scores live-scores.parquet \
  --expected expected-2.0.0.parquet --model-version 2.0.0 \
  --control-inputs control_inputs.parquet --ledger ledger.jsonl --out qc-report/
```

The outputs match `medagentrx check`: an HTML report with a Levey-Jennings chart, JSON with its own [published schema](https://github.com/a7med7emedan/medagentrx/blob/main/schema/qc-report.schema.json), a Markdown summary and JUnit XML. The GitHub Action and the GitLab component run it with `mode: qc`. `examples/sepsis-risk/qc/scheduled-qc.yml` is a complete daily workflow, and the dashboard shows each version's chart under **Deployment QC**.

From Python, `medagentrx.qc(...)` does the same, and `Guard.qc(...)` serves agents that operate the deployment.

QC runs never touch the locked test set, so they spend none of its evaluations.

## After a new release

When a new version passes `medagentrx check` and goes into service:

1. Score the control set with the new version, exactly as live requests will go.
2. Check that the control set is still the plan's and still disjoint from the new version's training data:

```bash
medagentrx qc init --control-inputs control_inputs.parquet \
  --scores expected-2.1.0.parquet --version 2.1.0 \
  --plan change-plan.yaml --manifest train_manifest_2.1.0.parquet
```

3. Record the release with its expected scores. LIVE-001 then expects 2.1.0, and LIVE-002 checks its expected score file against this record:

```bash
medagentrx ledger release ledger.jsonl --version 2.1.0 --qc-expected expected-2.1.0.parquet
```

The plan does not change. Its `expected_scores` covers the versions known when it was authorised; each later version's expected scores travel with its release record, which is hash-chained and signed with the ledger. Any change to the plan would break PLAN-001 for every later update, so a routine release must never need one. With `sd: null`, each version builds its own baseline.

Adding a `deployment_qc` block to a plan that is already in use is a change to the plan. It needs a new revision, and with it a new ledger, like any other plan change.

## False alarms and detection

The [validation results](validation.md#deployment-qc) quantify the rules under pure noise and under shifts of 0.5 to 3 SD. With daily runs of a stack that has real run-to-run noise, the full rule set gives about 2 to 7 false alarms a year, depending on how the SD was set. Treat an OUTSIDE_PLAN from QC as a reason to stop and investigate, as a laboratory does, and rerun the control set before concluding. A deterministic stack, which reproduces its scores exactly, gives none.

## Reference

Westgard J. O., Barry P. L., Hunt M. R., Groth T. A multi-rule Shewhart chart for quality control in clinical chemistry. Clinical Chemistry 1981;27(3):493 to 501.

<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Tutorial: from plan to evidence

This tutorial takes one model update through the whole life cycle: check the inputs, check the update, record the release, and send the evidence to a reviewer. It uses the synthetic sepsis example, so every command runs as written. The last section says what to replace for your own model.

It takes about fifteen minutes. You need Python 3.11 or later and git.

## 1. Install and get the example

```bash
pip install medagentrx
git clone https://github.com/a7med7emedan/medagentrx
cd medagentrx/examples/sepsis-risk
```

The folder holds one update of a sepsis risk score, from version 2.0.0 to 2.1.0:

| File | What it holds | Who makes it |
|---|---|---|
| `change-plan.yaml` | The approved change plan: which changes are allowed and how each is tested. | The regulatory and clinical team, once. |
| `intended-use.txt` | The intended-use statement; the plan pins its SHA-256. | The regulatory team, once. |
| `candidate.parquet` | Version 2.1.0's predictions on the locked test set. | The training pipeline. |
| `previous.parquet` | Version 2.0.0's predictions on the same rows. | Kept from the previous update. |
| `anchor.parquet` | The originally authorised version's predictions. | Kept from authorisation. |
| `train_manifest.parquet` | One row per training record of 2.1.0, with the fields the plan's inclusion rules use. | The training pipeline. |
| `model.yaml` | What 2.1.0 is: version, the version it replaces, the modification it applies, and SHA-256 hashes that bind it to its files. | The training pipeline. |

No model file is ever loaded. MedAgentRx reads predictions and metadata only.

## 2. Write a settings file

Every command below needs the same paths. Put them in `medagentrx.toml` once:

```toml
plan = "change-plan.yaml"
ledger = "ledger.jsonl"

[preflight]
candidate = "candidate.parquet"
previous = "previous.parquet"
anchor = "anchor.parquet"
manifest = "train_manifest.parquet"
model-meta = "model.yaml"

[check]
candidate = "candidate.parquet"
previous = "previous.parquet"
anchor = "anchor.parquet"
manifest = "train_manifest.parquet"
model-meta = "model.yaml"
out = "reports/2.1.0"
```

Anything on the command line still wins. The [command-line guide](cli.md#settings-file) explains the rules.

## 3. Check the plan

```bash
medagentrx validate change-plan.yaml
```

```text
valid: SEPSIS-RISK-PCCP revision 3
```

## 4. Check the inputs before spending a look

The locked test set may only be looked at a limited number of times, 20 for this plan. A typo in a path or a missing column should not cost one of them. `preflight` reads every input and checks its structure, without computing any metric:

```bash
medagentrx preflight
```

```text
  ok      plan: valid: SEPSIS-RISK-PCCP revision 3
  ok      model_meta: version 2.1.0 replaces 2.0.0 under modification M1
  ok      candidate: 20,000 rows
  ...
  ok      test_set: the candidate covers the locked test set
  ok      manifest: 30,000 training rows
  ok      ledger: not found; check will create it
ready: medagentrx check can run
```

Every problem is listed at once, so fix them all and run it again.

## 5. Check the update

```bash
medagentrx check
echo $?
```

```text
verdict: ACCEPTED
report: /path/to/sepsis-risk/reports/2.1.0/report.html
...
ledger: entry 0 6aea5bfc5304
0
```

The exit code is the verdict: 0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN. Open `reports/2.1.0/report.html` in a browser. It works offline.

Run the check once more, with `--verbose` before the command to see every check, and the reports in another folder:

```bash
medagentrx --verbose check --out reports/second-try
```

```text
verdict: OUTSIDE_PLAN
  PASS PLAN-001: Plan is valid and unchanged
  PASS PLAN-002: Modification M1 is in the plan
  PASS PLAN-003: Intended-use statement matches the plan
  FAIL PLAN-004: 1 update(s) already released this quarter; the plan allows 1
  ...
```

The second attempt is recorded too, and it is outside the plan: the plan allows one update per quarter, and 2.1.0 was accepted a moment ago. Every attempt counts, which is the point of the ledger.

To learn what a check enforces:

```bash
medagentrx explain PLAN-004
```

## 6. Record the release and update the model card

When version 2.1.0 goes into service, record it, and add its performance to the model card:

```bash
medagentrx card change-plan.yaml --report reports/2.1.0/report.json --out MODEL_CARD.md --ledger ledger.jsonl
medagentrx ledger release ledger.jsonl --version 2.1.0
medagentrx ledger show ledger.jsonl
```

## 7. Change the plan, and see what changed

Plans change rarely, and each change needs a new revision and new regulatory review. Before a revised plan is submitted, compare it with the approved one. Here a copy with a wider AUROC margin stands in for the revision:

```bash
sed -e 's/margin: 0.02/margin: 0.03/' -e 's/revision: 3 /revision: 4 /' change-plan.yaml > change-plan-r4.yaml
medagentrx plan-diff change-plan.yaml change-plan-r4.yaml
```

```text
~ performance.criteria[0].margin: 0.02 -> 0.03
~ plan.revision: 3 -> 4
2 change(s); fingerprint 50e5f1c2f5ae279b -> e560c9aacf5e42ef
```

Comments and formatting do not count; only meaning does.

## 8. Send the evidence

A reviewer, auditor or notified body needs the plan, the ledger and the reports, and a way to check nothing was altered. One command bundles them:

```bash
medagentrx bundle create --reports reports/2.1.0 --out evidence-2.1.0.zip
```

The zip holds the plan and its PCCP document, the ledger and its head, the reports, and `MANIFEST.json` with the SHA-256 of every file. Only an intact ledger is bundled. The recipient checks it with:

```bash
medagentrx bundle verify evidence-2.1.0.zip
```

```text
ok: 9 files match the manifest; ledger intact; plan SEPSIS-RISK-PCCP revision 3
```

For a spreadsheet of every decision:

```bash
medagentrx ledger export ledger.jsonl --format csv --out decisions.csv
```

## 9. Your own model

Replace the example files with your own. The order matters, because some files pin the hashes of others.

1. **Write the plan.** `medagentrx init` asks a few questions and writes a commented `change-plan.yaml`. The [change plan reference](plan-reference.md) describes every key.
2. **Size the locked test set**, before you lock it: `medagentrx sample-size change-plan.yaml --auroc 0.80 --prevalence 0.12`.
3. **Export predictions** of each version on the locked test set, as Parquet or CSV. Required columns: `row_id` (unique text), `y_true` (0 or 1) and `y_score` (a probability from 0 to 1). Add the subgroup columns the plan names, and in the candidate file the keys listed in `forbid_overlap_on`, such as `patient_id`.
4. **Fingerprint the locked test set** and put the result in `data_management.locked_test_set.sha256`: `medagentrx fingerprint candidate.parquet`. It depends only on the rows and labels, so every version's file gives the same value.
5. **Write the training manifest**: one row per training record, with `row_id`, `patient_id` and the fields `training_inclusion` uses.
6. **Describe the candidate** in `model.yaml`. The hashes come from `shasum -a 256 FILE` (or `sha256sum FILE` on Linux):

    ```yaml
    version: 2.1.0
    previous_version: 2.0.0
    modification_id: M1                 # must be listed in the plan
    architecture_sha256: "<SHA-256 of the architecture definition>"
    intended_use_sha256: "<SHA-256 of intended-use.txt>"
    trained_at: "2026-04-01T08:00:00+00:00"
    training_manifest_sha256: "<SHA-256 of train_manifest.parquet>"
    predictions_sha256: "<SHA-256 of candidate.parquet>"
    ```

7. **Run `preflight`, then `check`**, as above. Keep `ledger.jsonl` and `ledger.jsonl.head` between runs, for example in version control: a fresh ledger would reset the plan's budgets.

## Where next

- [Deployment QC](qc.md): check on a schedule that the live system still behaves like the released version.
- [CI guides](ci.md): run the check on every pull request in GitHub Actions or GitLab.
- [For agents and AutoML](agents.md): let an agent propose updates without fitting the test set.
- [For reviewers](reviewers.md): read a report and verify a ledger or a bundle.

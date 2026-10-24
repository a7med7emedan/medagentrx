<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Command line

| Command | What it does |
|---|---|
| `medagentrx init` | Ask a few questions and write a commented `change-plan.yaml`. |
| `medagentrx schema` | Print the JSON Schema of the plan. |
| `medagentrx validate PLAN...` | Check one or more plans against the schema and their own logic. |
| `medagentrx fingerprint TEST_PREDS` | Print the canonical fingerprint of the locked test set. |
| `medagentrx sample-size [PLAN] --auroc A --prevalence P` | Rows the locked test set needs for the plan's power. |
| `medagentrx check PLAN --candidate ... --ledger ... --out DIR` | Check one update, record it in the ledger and write the reports. |
| `medagentrx render-plan PLAN --out DIR` | Write the PCCP document in Markdown and HTML. |
| `medagentrx card PLAN --report DIR/report.json --out MODEL_CARD.md [--ledger LEDGER]` | Add an accepted version's performance to the model card, and record the update in the ledger. |
| `medagentrx ledger release LEDGER --version V [--qc-expected FILE]` | Record that an accepted version was put into service, with its expected deployment QC scores. |
| `medagentrx qc init --control-inputs RAW --scores EXPECTED --version V` | Fingerprint a QC control set and print the plan's `deployment_qc` block. With `--plan`, print the release command for a new version. |
| `medagentrx qc run PLAN --scores LIVE --expected EXPECTED --model-version V --ledger L --out DIR` | Judge one deployment QC run of the live system and record it. |
| `medagentrx ledger verify LEDGER [--public-key KEY] [--plan PLAN]` | Recompute the hash chain, compare it with the head, and check the head signature against the plan's key. |
| `medagentrx ledger show LEDGER` | List every evaluation and the budgets used. |
| `medagentrx ledger keygen --out DIR` | Write an Ed25519 key pair for signing ledger heads and print its fingerprint. |
| `medagentrx demo [--out DIR]` | Run the planted scenarios on synthetic data. |
| `medagentrx serve --ledger LEDGER` | Serve the read-only dashboard on 127.0.0.1 (extra `[web]`). |
| `medagentrx version` | Print the version. |

Run any command with `--help` for its options.

## Exit codes

| Code | `check` | `qc run` | Other commands |
|---|---|---|---|
| 0 | ACCEPTED | IN_CONTROL | success |
| 1 | FAILED | | `ledger verify`: the ledger fails verification; `demo`: a scenario did not match |
| 2 | OUTSIDE_PLAN | OUTSIDE_PLAN | |
| 3 | input or usage error | input or usage error | input or usage error |

Mistakes in inputs are reported in plain text, never as a traceback.

## Limits

`check` and `fingerprint` accept `--max-file-bytes` (default 1 GiB) and `--max-rows` (default ten million). Larger inputs are refused before they are read.

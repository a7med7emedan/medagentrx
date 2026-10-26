<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

<!-- This page is written by scripts/make_docs.py. Edit the code, not this file. -->

# Command-line reference

Every command, argument and option, generated from the parser itself. The [command-line guide](cli.md) explains exit codes, global options, settings files and JSON output.

## Global options

Global options go before the command, for example `medagentrx --quiet check ...`.

| Option | Description |
|---|---|
| `--version`, `-V` | Print the version and exit. |
| `--quiet`, `-q` | Print only errors and requested output; exit codes still tell. |
| `--verbose` | Print every check, not only failures and warnings. |
| `--install-completion` | Install completion for the current shell. |
| `--show-completion` | Show completion for the current shell, to copy it or customize the installation. |

## medagentrx version

```text
medagentrx version [OPTIONS]
```

Print the installed version.

## medagentrx schema

```text
medagentrx schema [OPTIONS]
```

Print the JSON Schema of the change plan.

## medagentrx validate

```text
medagentrx validate [OPTIONS] PLAN...
```

Check change plans against the schema and their own logic.

Exit codes: 0 every plan is valid, 3 at least one is not.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `PLAN...` | path, repeatable | required | One or more change-plan.yaml files. |
| `--verbose`, `-v` | flag |  | Also print the plan fingerprint. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |

## medagentrx fingerprint

```text
medagentrx fingerprint [OPTIONS] TEST_PREDS
```

Print the canonical fingerprint of the locked test set.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `TEST_PREDS` | path | required | Prediction file on the locked test set. |
| `--max-file-bytes` | integer (value>=1) | `1073741824` | Largest input file accepted, in bytes. |
| `--max-rows` | integer (value>=1) | `10000000` | Largest number of rows in one input file. |

## medagentrx sample-size

```text
medagentrx sample-size [OPTIONS] [PLAN]
```

Size the locked test set so the AUROC criterion has the power the plan asks for.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--auroc` | number | required | Expected AUROC of the deployed version. |
| `--prevalence` | number | required | Share of positives in the test population. |
| `PLAN` | path |  | Change plan to read the margin, level and power from. |
| `--margin` | number |  | Non-inferiority margin; overrides the plan. |
| `--alpha` | number |  | One-sided level per update; overrides the plan. |
| `--power` | number |  | Target power; overrides the plan. |
| `--correlation` | number | `0.6` | Correlation of the two AUROC estimates; 0.5 to 0.8 is typical for retraining. |
| `--true-difference` | number | `0.0` | AUROC change the candidate is expected to have. |

## medagentrx check

```text
medagentrx check [OPTIONS] PLAN
```

Check one model update against its change plan and record the decision.

Run medagentrx preflight first to check the input files without spending a look.

Exit codes: 0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN, 3 input or usage error.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `PLAN` | path | required | Path to change-plan.yaml. |
| `--candidate` | path | required | Candidate predictions. |
| `--previous` | path | required | Predictions of the version replaced. |
| `--anchor` | path | required | Predictions of the authorised version. |
| `--manifest` | path | required | Training data manifest. |
| `--model-meta` | path | required | Candidate model.yaml. |
| `--ledger` | path | required | Decision ledger, created if missing. |
| `--out` | path | required | Directory for the reports. |
| `--seed` | int | `0` | Seed for every resampling step. |
| `--replicates` | integer (value>=100) | `2000` | Bootstrap replicates. |
| `--format` | str | `html,json,md,junit` | Report formats, comma separated: html,json,md,junit. |
| `--signing-key` | path |  | Ed25519 private key that signs the ledger head. Environment variable `MEDAGENTRX_SIGNING_KEY`. |
| `--max-file-bytes` | integer (value>=1) | `1073741824` | Largest input file accepted, in bytes. |
| `--max-rows` | integer (value>=1) | `10000000` | Largest number of rows in one input file. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |
| `--notify` | str |  | HTTPS webhook (Slack, Teams or any JSON endpoint) told about the verdict. Environment variable `MEDAGENTRX_NOTIFY_URL`. |
| `--notify-on` | str | `problems` | problems: only when the verdict is not good or a check warns; always: every run. |
| `--notify-format` | str | `auto` | auto (from the URL), slack, teams or json. |

## medagentrx preflight

```text
medagentrx preflight [OPTIONS] PLAN
```

Check an update's input files without evaluating it.

Reads every file medagentrx check would read and checks its structure. It
computes no metric, spends no look at the locked test set and records
nothing, so it can run as often as needed.

Exit codes: 0 ready, 1 not ready, 3 usage error.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `PLAN` | path | required | Path to change-plan.yaml. |
| `--candidate` | path | required | Candidate predictions. |
| `--previous` | path | required | Predictions of the version replaced. |
| `--anchor` | path | required | Predictions of the authorised version. |
| `--manifest` | path | required | Training data manifest. |
| `--model-meta` | path | required | Candidate model.yaml. |
| `--ledger` | path |  | Decision ledger: verify it and report the budgets left. |
| `--public-key` | path |  | Require a valid ledger head signature by this key. |
| `--max-file-bytes` | integer (value>=1) | `1073741824` | Largest input file accepted, in bytes. |
| `--max-rows` | integer (value>=1) | `10000000` | Largest number of rows in one input file. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |

## medagentrx explain

```text
medagentrx explain [OPTIONS] [CHECK...]
```

Explain what a check enforces, or list every check.

Exit codes: 0 success, 3 unknown check.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `CHECK...` | str, repeatable |  | Check identifiers, for example PERF-001. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |

## medagentrx plan-diff

```text
medagentrx plan-diff [OPTIONS] OLD NEW
```

Show what changed between two change plans, key by key.

Comments, key order and quoting do not count: both plans are validated and
their meaning is compared. A new plan revision needs a new ledger.

Exit codes: 0 the plans mean the same, 1 they differ, 3 a plan is not valid.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `OLD` | path | required | The earlier change plan. |
| `NEW` | path | required | The later change plan. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |

## medagentrx render-plan

```text
medagentrx render-plan [OPTIONS] PLAN
```

Write the PCCP document (FDA components and EU cross-reference) from the plan.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `PLAN` | path | required | Path to change-plan.yaml. |
| `--out` | path | required | Directory for the PCCP document. |
| `--format` | str | `md,html` | Document formats, comma separated: md,html. |

## medagentrx card

```text
medagentrx card [OPTIONS] PLAN
```

Add or replace this version's performance section in the model card.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `PLAN` | path | required | Path to change-plan.yaml. |
| `--report` | path | required | report.json of an accepted update. |
| `--out` | path | required | Model card file to create or update. |
| `--ledger` | path |  | Record the card update in this ledger (DOC-001). |
| `--signing-key` | path |  | Ed25519 private key that signs the ledger head. Environment variable `MEDAGENTRX_SIGNING_KEY`. |

## medagentrx demo

```text
medagentrx demo [OPTIONS]
```

Run the planted scenarios on synthetic data and check each verdict.

The update scenarios come first, then the deployment QC scenarios.
Exit codes: 0 every scenario gave its expected verdict, 1 otherwise.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--out` | path | `medagentrx-demo` | Directory for the scenario files and reports. |
| `--scenario` | str, repeatable |  | Run only this scenario. Repeat for more. |
| `--replicates` | integer (value>=100) | `2000` | Bootstrap replicates. |

## medagentrx serve

```text
medagentrx serve [OPTIONS]
```

Serve a read-only dashboard of the ledger and reports (needs the web extra).

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--ledger` | path | required | Decision ledger to show. |
| `--reports` | path |  | Folder searched for report.json files. |
| `--plan` | path |  | Change plan, for budget limits. |
| `--host` | str | `127.0.0.1` | Address to bind. |
| `--port` | integer (1<=value<=65535) | `8765` | Port to bind. |

## medagentrx init

```text
medagentrx init [OPTIONS]
```

Write a commented starter change-plan.yaml.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--out`, `-o` | path | `change-plan.yaml` | Where to write the plan. |
| `--defaults` | flag |  | Use default answers without prompting. |
| `--force` | flag |  | Overwrite an existing file. |

## medagentrx ledger verify

```text
medagentrx ledger verify [OPTIONS] LEDGER
```

Recompute the hash chain and compare it with the recorded head.

Exit codes: 0 intact, 1 fails verification, 3 input or usage error.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `LEDGER` | path | required | Path to ledger.jsonl. |
| `--head` | path |  | Head file. Defaults to LEDGER.head. |
| `--public-key` | path |  | Require a valid head signature by this public key. |
| `--plan` | path |  | Change plan whose pinned signing key the head must match. |

## medagentrx ledger keygen

```text
medagentrx ledger keygen [OPTIONS]
```

Create an Ed25519 key pair for signing ledger heads.

Keep ledger-signing.key secret, for example as a CI secret. Commit
ledger-signing.pub, and put the printed fingerprint in the plan as
ledger_signing_key_sha256. Set MEDAGENTRX_SIGNING_KEY_PASSPHRASE to encrypt
the private key.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--out` | path | `.` | Folder for the key pair. |

## medagentrx ledger release

```text
medagentrx ledger release [OPTIONS] LEDGER
```

Record that an accepted version was put into service.

With --qc-expected, the release record also binds the version's expected
QC scores, so deployment QC can check it without a change to the plan.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `LEDGER` | path | required | Path to ledger.jsonl. |
| `--version` | str | required | Accepted version put into service. |
| `--qc-expected` | path |  | Expected scores of this version on the deployment QC control set. |
| `--signing-key` | path |  | Ed25519 private key that signs the ledger head. Environment variable `MEDAGENTRX_SIGNING_KEY`. |

## medagentrx ledger show

```text
medagentrx ledger show [OPTIONS] LEDGER
```

List every entry in the ledger, oldest first.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `LEDGER` | path | required | Path to ledger.jsonl. |

## medagentrx ledger export

```text
medagentrx ledger export [OPTIONS] LEDGER
```

Export every ledger entry as one table row, for audits and spreadsheets.

The ledger is verified first; a ledger that fails verification is not
exported. Text that a spreadsheet would run as a formula is quoted.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `LEDGER` | path | required | Path to ledger.jsonl. |
| `--format` | str | `csv` | csv (for spreadsheets) or json. |
| `--out`, `-o` | path |  | File to write. Defaults to standard output. |

## medagentrx qc init

```text
medagentrx qc init [OPTIONS]
```

Fingerprint a control set and print the deployment_qc block for the plan.

After a new release, run it again with --plan and --version: it checks the
control set is the plan's and prints the ledger release command that records
the new version's expected scores.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--control-inputs` | path | required | Raw control records with a row_id column. |
| `--scores` | path | required | Expected scores of VERSION on the control set. |
| `--version` | str | required | Version the scores belong to. |
| `--test-set` | path |  | Locked test-set predictions; control ids must differ. |
| `--manifest` | path |  | Training manifest; control ids must differ. |
| `--plan` | path |  | Plan with a deployment_qc block: print the new version's release command. |
| `--tolerance` | number (1e-12<=value<=1.0) | `1e-06` | Largest per-record difference allowed. |
| `--max-file-bytes` | integer (value>=1) | `1073741824` | Largest input file accepted, in bytes. |
| `--max-rows` | integer (value>=1) | `10000000` | Largest number of rows in one input file. |

## medagentrx qc run

```text
medagentrx qc run [OPTIONS] PLAN
```

Judge one QC run of the live system and record it.

Exit codes: 0 IN_CONTROL, 2 OUTSIDE_PLAN, 3 input or usage error.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `PLAN` | path | required | Path to change-plan.yaml. |
| `--scores` | path | required | Live system's scores on the control set. |
| `--expected` | path | required | Expected scores of the model version. |
| `--model-version` | str | required | Version the live system reports. |
| `--ledger` | path | required | Decision ledger, created if missing. |
| `--out` | path | required | Directory for the reports. |
| `--control-inputs` | path |  | Raw control file, checked against the plan. |
| `--format` | str | `html,json,md,junit` | Report formats, comma separated: html,json,md,junit. |
| `--signing-key` | path |  | Ed25519 private key that signs the ledger head. Environment variable `MEDAGENTRX_SIGNING_KEY`. |
| `--max-file-bytes` | integer (value>=1) | `1073741824` | Largest input file accepted, in bytes. |
| `--max-rows` | integer (value>=1) | `10000000` | Largest number of rows in one input file. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |
| `--notify` | str |  | HTTPS webhook (Slack, Teams or any JSON endpoint) told about the verdict. Environment variable `MEDAGENTRX_NOTIFY_URL`. |
| `--notify-on` | str | `problems` | problems: only when the verdict is not good or a check warns; always: every run. |
| `--notify-format` | str | `auto` | auto (from the URL), slack, teams or json. |

## medagentrx bundle create

```text
medagentrx bundle create [OPTIONS]
```

Write an evidence bundle for a reviewer, auditor or notified body.

The zip holds the plan and its PCCP document, the ledger and its head, the
public key and the reports, with MANIFEST.json listing the SHA-256 of every
file. Only an intact ledger is bundled.

Exit codes: 0 written, 1 the ledger fails verification, 3 input or usage error.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `--plan` | path | required | Path to change-plan.yaml. |
| `--ledger` | path | required | Decision ledger. |
| `--out`, `-o` | path | `medagentrx-evidence.zip` | Zip file to write. |
| `--reports` | path, repeatable |  | Folder of reports to include. Repeat for more. |
| `--public-key` | path |  | Ledger signing public key; needed when the plan pins one. |

## medagentrx bundle verify

```text
medagentrx bundle verify [OPTIONS] BUNDLE
```

Check a received bundle: every file against its SHA-256, and the ledger chain.

Exit codes: 0 intact, 1 it does not check out, 3 input or usage error.

| Argument or option | Type | Default | Description |
|---|---|---|---|
| `BUNDLE` | path | required | Evidence bundle zip. |
| `--public-key` | path |  | Also require a valid ledger head signature by this key. |
| `--json` | flag |  | Print the result as JSON on stdout, for scripts and agents. |

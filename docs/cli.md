<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Command line

This page explains how the command line behaves. The [command-line reference](cli-reference.md) lists every argument and option of every command, and `medagentrx COMMAND --help` prints the same in the terminal.

## Commands

| Command | What it does |
|---|---|
| `medagentrx init` | Ask a few questions and write a commented `change-plan.yaml`. |
| `medagentrx validate PLAN...` | Check one or more plans against the schema and their own logic. |
| `medagentrx schema` | Print the JSON Schema of the plan. |
| `medagentrx sample-size [PLAN] --auroc A --prevalence P` | Rows the locked test set needs for the plan's power. |
| `medagentrx fingerprint TEST_PREDS` | Print the canonical fingerprint of the locked test set. |
| `medagentrx preflight PLAN --candidate ...` | Check an update's input files without evaluating it, and report the budgets left. |
| `medagentrx check PLAN --candidate ... --ledger ... --out DIR` | Check one update, record it in the ledger and write the reports. |
| `medagentrx explain [CHECK...]` | Explain what a check enforces, or list every check. |
| `medagentrx card PLAN --report DIR/report.json --out MODEL_CARD.md` | Add an accepted version's performance to the model card, and record it in the ledger with `--ledger`. |
| `medagentrx render-plan PLAN --out DIR` | Write the PCCP document in Markdown and HTML. |
| `medagentrx plan-diff OLD NEW` | Show what changed between two plans, key by key. |
| `medagentrx qc init --control-inputs RAW --scores EXPECTED --version V` | Fingerprint a QC control set and print the plan's `deployment_qc` block. |
| `medagentrx qc run PLAN --scores LIVE --expected EXPECTED --model-version V ...` | Judge one deployment QC run of the live system and record it. |
| `medagentrx ledger verify LEDGER` | Recompute the hash chain and check the head and its signature. |
| `medagentrx ledger show LEDGER` | List every entry and the budgets used. |
| `medagentrx ledger export LEDGER --format csv` | Write every entry as a table row, for audits and spreadsheets. |
| `medagentrx ledger release LEDGER --version V` | Record that an accepted version was put into service. |
| `medagentrx ledger keygen --out DIR` | Write an Ed25519 key pair for signing ledger heads. |
| `medagentrx bundle create --plan PLAN --ledger LEDGER --reports DIR` | Write an evidence bundle: plan, ledger and reports in one checkable zip. |
| `medagentrx bundle verify BUNDLE` | Check a received bundle against its manifest and verify its ledger. |
| `medagentrx demo` | Run the planted scenarios on synthetic data. |
| `medagentrx serve --ledger LEDGER` | Serve the read-only dashboard on 127.0.0.1 (extra `[web]`). |

## Exit codes

| Code | `check` | `qc run` | `preflight` | `plan-diff` | Other commands |
|---|---|---|---|---|---|
| 0 | ACCEPTED | IN_CONTROL | ready | plans mean the same | success |
| 1 | FAILED | | not ready | plans differ | `ledger verify`, `ledger export`, `bundle`: the ledger or bundle does not check out; `demo`: a scenario did not match |
| 2 | OUTSIDE_PLAN | OUTSIDE_PLAN | | | |
| 3 | input or usage error | input or usage error | usage error | a plan is not valid | input or usage error |

Mistakes in inputs are reported in plain text, never as a traceback.

## Global options

Global options go before the command.

| Option | Effect |
|---|---|
| `--version`, `-V` | Print the version and exit. |
| `--quiet`, `-q` | Print only errors and the output a command exists to give, such as a fingerprint or JSON. The exit code still carries the verdict. |
| `--verbose` | Print every check, not only failures and warnings. |

```bash
medagentrx --quiet check change-plan.yaml ...    # silent, the exit code tells
medagentrx --verbose qc run change-plan.yaml ...  # every LIVE check, passed or not
```

## Check the inputs first

`medagentrx preflight` reads every file `check` would read and reports each problem it finds: an invalid plan, a model card claiming a modification the plan does not list, a missing column, prediction files whose rows or labels differ, a candidate that is not the locked test set, an unreadable manifest, a ledger that fails verification or a spent budget. It computes no metric, spends no look at the locked test set and records nothing, so it can run as often as needed.

```bash
medagentrx preflight change-plan.yaml \
  --candidate candidate.parquet --previous previous.parquet --anchor anchor.parquet \
  --manifest train_manifest.parquet --model-meta model.yaml --ledger ledger.jsonl
```

## Settings file

Options repeated on every run can live in a settings file, so a routine check becomes `medagentrx check`. MedAgentRx reads `medagentrx.toml` in the current folder, or the `[tool.medagentrx]` table of `pyproject.toml` when there is no `medagentrx.toml`.

```toml
# medagentrx.toml
plan = "change-plan.yaml"          # every command with a plan or --plan option
ledger = "governance/ledger.jsonl" # every command with a ledger or --ledger option

[check]
candidate = "predictions/candidate.parquet"
previous = "predictions/previous.parquet"
anchor = "predictions/anchor.parquet"
manifest = "data/train_manifest.parquet"
model-meta = "model.yaml"
out = "reports/latest"

[qc.run]
scores = "qc/live-scores.parquet"
expected = "qc/expected-2.0.0.parquet"
model-version = "2.0.0"
out = "reports/qc"
```

- Keys at the top apply to every command that has an option of that name. A table applies to one command; `[qc.run]` is `medagentrx qc run`.
- Keys are option names, with or without dashes: `model-meta` and `model_meta` are the same.
- Relative paths are relative to the settings file, not the current folder.
- An option on the command line wins over an environment variable, which wins over the settings file.
- An unknown key is an error, so a typo never goes unnoticed.
- `MEDAGENTRX_CONFIG=path/to/file.toml` reads another file. `MEDAGENTRX_CONFIG=` (empty) turns settings off.

Keep secrets out of the settings file. The signing key path may go there, but the key itself stays in a protected secret.

## JSON output

`check`, `qc run`, `preflight`, `validate`, `plan-diff`, `explain` and `bundle verify` take `--json`. The result is then printed as JSON on standard output, and the exit code is unchanged. Scripts, CI jobs and agents can read the verdict without parsing text.

```bash
medagentrx check change-plan.yaml ... --json | jq -r .verdict
```

For `check`, the JSON holds `verdict`, `exit_code`, `plan`, `candidate_version`, `previous_version`, `touched_test_set`, one item per check with its `id`, `status` and `message`, the report paths and the new ledger entry. `qc run` adds the run bias, the largest deviation and the multirule rules that fired. The full record, with every number, stays in `report.json`, which has a [published schema](https://github.com/a7med7emedan/medagentrx/blob/main/schema/report.schema.json).

## Notifications

`check` and `qc run` can tell a chat channel or an incident system about the verdict. Give an HTTPS webhook URL with `--notify`, or better in the `MEDAGENTRX_NOTIFY_URL` environment variable, because a webhook URL is a secret.

```bash
export MEDAGENTRX_NOTIFY_URL="https://hooks.slack.com/services/..."
medagentrx qc run change-plan.yaml ...
```

| Option | Values | Default |
|---|---|---|
| `--notify-on` | `problems`: only when the verdict is not ACCEPTED or IN_CONTROL, or a check warns. `always`: every run. | `problems` |
| `--notify-format` | `slack`, `teams` (Microsoft Teams Workflows), `json`, or `auto` to choose from the URL. | `auto` |

The message names the command, the verdict, the plan, the version and the failed checks. It never carries data rows. This is the only network call MedAgentRx makes, and it is off unless a URL is given. The URL must use HTTPS, redirects are refused, and the URL is never printed or written to a report or the ledger. A notification that fails is a warning: the verdict and the exit code stay the same. For email, point the webhook at your incident or mail service.

## Tab completion

```bash
medagentrx --install-completion   # bash, zsh, fish or PowerShell
```

Open a new terminal. Commands, options and file names then complete with the Tab key.

## Limits

`check`, `preflight`, `qc` and `fingerprint` accept `--max-file-bytes` (default 1 GiB) and `--max-rows` (default ten million). Larger inputs are refused before they are read.

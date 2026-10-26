<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# For reviewers

## Check an evidence bundle

Manufacturers can send the plan, the ledger and the reports as one zip, made with `medagentrx bundle create`. Check it before reading anything in it:

```bash
pip install medagentrx
medagentrx bundle verify evidence.zip
medagentrx bundle verify evidence.zip --public-key ledger-signing.pub
```

`verify` checks every file against the SHA-256 in `MANIFEST.json`, reports any file added, removed or changed, and recomputes the ledger's hash chain. With `--public-key`, the ledger head must also carry a valid signature by that key. Nothing is run and nothing is extracted except the ledger, which is checked in a temporary folder. The exit code is 0 when everything checks out and 1 otherwise.

## Read a report

`report.html` opens offline and loads nothing from the network.

1. **Verdict banner.** ACCEPTED, FAILED or OUTSIDE_PLAN, with one sentence on what it means.
2. **Summary.** Failed checks, warnings, the alpha this evaluation used, and the key numbers.
3. **Checks table.** One row per check, with the result and what a failure does to the verdict.
4. **Figures.**
    - The update timeline shows AUROC per version against the anchor and the drift budget.
    - The forest plot shows each subgroup's change with its interval at the level it was tested.
    - The calibration and decision curves compare candidate and previous version.
    - The gauges show how much of each plan budget is used.
5. **Check details.** Every number behind every check.
6. **Environment and inputs.** Tool and library versions, seed, and the SHA-256 of every input file.

`report.json` holds the same content in a [published schema](https://github.com/a7med7emedan/medagentrx/blob/main/schema/report.schema.json).

## Match files to a decision

Each ledger entry and report records the SHA-256 of the plan, the three prediction files, the training manifest and the model metadata. Hash the files you were given and compare.

```bash
shasum -a 256 change-plan.yaml candidate.parquet model.yaml
medagentrx fingerprint candidate.parquet
```

## Verify the ledger

```bash
medagentrx ledger verify ledger.jsonl --head trusted-copy/ledger.jsonl.head
medagentrx ledger verify ledger.jsonl --public-key ledger-signing.pub --plan change-plan.yaml
medagentrx ledger show ledger.jsonl
```

`verify` recomputes every hash and checks the chain against the head file. Edited, reordered or removed entries are reported, as are entries out of time order. When the plan pins a signing key, `--public-key` checks the head's signature, and `--plan` checks that the key is the one `ledger_signing_key_sha256` names. A signature does not rule out a rollback to an older signed head, so compare the entry count with a head you trust. The [ledger page](ledger.md) explains the format.

To read every decision as a spreadsheet:

```bash
medagentrx ledger export ledger.jsonl --format csv --out decisions.csv
```

The export is refused for a ledger that fails verification. Text a spreadsheet would run as a formula is quoted, so the file is safe to open.

## Read the plan itself

```bash
medagentrx render-plan change-plan.yaml --out pccp/
```

This writes the plan as an FDA PCCP document with the EU cross-reference. It comes from the same file the gate runs.

## See what changed in a revised plan

```bash
medagentrx plan-diff change-plan-r3.yaml change-plan-r4.yaml
```

Each changed key is listed with its old and new value, for example a wider AUROC margin or a new modification. Both plans are validated first, so comments and formatting do not count. A content change without a new revision number is flagged.

## Look up a check

```bash
medagentrx explain PERF-005
```

This prints what the check enforces, what a failure does to the verdict and its regulatory cross-reference. The [checks catalogue](checks.md) has the same for every check.

<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# For reviewers

## Read a report

`report.html` opens offline and loads nothing from the network.

1. **Verdict banner.** ACCEPTED, FAILED or OUTSIDE_PLAN, with one sentence on what it means.
2. **Summary.** Failed checks, warnings, the alpha this evaluation used, and the key numbers.
3. **Checks table.** One row per check, with the result and what a failure does to the verdict.
4. **Figures.**
    - The update timeline shows AUROC per version against the anchor and the drift budget.
    - The forest plot shows each subgroup's change with its adjusted interval.
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
medagentrx ledger show ledger.jsonl
```

`verify` recomputes every hash and checks the chain against the head file. Edited, reordered or removed entries are reported. The [ledger page](ledger.md) explains the format.

## Read the plan itself

```bash
medagentrx render-plan change-plan.yaml --out pccp/
```

This writes the plan as an FDA PCCP document with the EU cross-reference. It comes from the same file the gate runs.

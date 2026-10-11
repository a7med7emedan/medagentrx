<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Decision ledger

Every evaluation under a plan is written to `ledger.jsonl`, including failed ones. The plan's budgets are read back from it: looks at the locked test set, released updates, release frequency and alpha. Because failures count too, neither a person nor an agent can keep trying candidates until one passes by chance.

## What an entry holds

Each line is one JSON object:

- `seq`, `prev_hash` and `hash` form the chain. `hash` is the SHA-256 of the entry's canonical JSON (sorted keys, no spaces) without the `hash` field.
- `plan` names the plan id, revision and fingerprint.
- `candidate_version`, `previous_version` and `modification_id` describe the update.
- `verdict`, `failed_checks` and `warnings` record the outcome.
- `touched_test_set` says whether this evaluation spent a look at the locked test set.
- `alpha.used` is the level spent, and `alpha.state_after` is the alpha accounting after this entry.
- `inputs` holds the SHA-256 of every input file, so a reviewer can match files to decisions.

An evaluation with an invalid plan file is reported as OUTSIDE_PLAN but not written, because it cannot be attributed to a plan.

## Head file

`ledger.jsonl.head` records the number of entries and the last hash. Removing entries from the end of the ledger leaves a valid chain, but it no longer matches the head. For the strongest guarantee, keep a copy of the head where the ledger's writers cannot change it, such as a CI artifact or a commit.

## Verifying

```bash
medagentrx ledger verify ledger.jsonl
medagentrx ledger verify ledger.jsonl --head /trusted/copy/ledger.jsonl.head
medagentrx ledger show ledger.jsonl
```

`verify` exits with 0 when the chain and head agree, 1 when they do not, and 3 for an input or usage error. `check` refuses to use, or append to, a ledger that fails verification.

## Concurrency

`check` holds a lock file, `ledger.jsonl.lock`, from reading the budgets until the new entry is written. Two evaluations therefore cannot both spend the last look. An evaluation that read an older ledger is refused on append and must be run again. If a crash leaves the lock file behind, remove it once no evaluation is running.

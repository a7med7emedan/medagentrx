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
- `kind` is `evaluation` for a formal check and `guard` for an agent's look. Guard entries spend a look but no alpha, and `answer` records what the agent was told.

Times must not run backwards. `check` refuses an evaluation dated before the last entry, and `verify` reports any entry recorded before the one it follows. Without this, setting the clock back would let updates slip past the plan's frequency limit.

An evaluation with an invalid plan file is reported as OUTSIDE_PLAN but not written, because it cannot be attributed to a plan.

## Accepted, carded, in service

An ACCEPTED verdict authorises a release. The plan's update count and frequency limits count acceptances, whether or not the version goes into service. Holding an acceptance back therefore cannot be used to get round a limit. Two kinds of record, each tied to the accepted evaluation by its sequence number and hash, say what happened next:

```bash
medagentrx card change-plan.yaml --report report/report.json --out MODEL_CARD.md --ledger ledger.jsonl
medagentrx ledger release ledger.jsonl --version 2.1.0
```

- `card` writes the version's section into the model card and records the card's SHA-256. When the plan requires model card updates, DOC-001 fails the next update until the card for the previous accepted version is recorded.
- `release` records that the version was put into service.

Each version takes at most one record of each kind, and only after an ACCEPTED evaluation of that version. A card record also requires the report to be of the candidate file that was accepted.

## Head file

`ledger.jsonl.head` records the number of entries and the last hash. Removing entries from the end of the ledger leaves a valid chain, but it no longer matches the head. For the strongest guarantee, keep a copy of the head where the ledger's writers cannot change it, such as a CI artifact or a commit.

## Signed heads

A hash chain shows that entries were edited. It cannot stop someone who can write both the ledger and its head from rewriting the whole chain. A signed head stops that: without the key, nobody can produce a valid head for altered history. The signing key stays with a trusted party, such as a CI secret, and anyone can verify with the public key.

```bash
medagentrx ledger keygen --out keys/
```

This writes `ledger-signing.key` with owner-only permissions and `ledger-signing.pub`, and prints the key fingerprint. Windows has no POSIX permissions, so restrict the key file there with the folder's access control list. Set `MEDAGENTRX_SIGNING_KEY_PASSPHRASE` before running it to encrypt the private key. Pin the key in the plan:

```yaml
ledger_signing_key_sha256: "<fingerprint printed by keygen>"
```

With the key pinned, `check` and the guard refuse to run without the matching key, given by `--signing-key` or `MEDAGENTRX_SIGNING_KEY`. Each head then carries an Ed25519 signature over the entry count, the last hash and the key fingerprint. Because the fingerprint is part of the plan, changing the key changes the plan, and PLAN-001 reports it.

Start signing with a new ledger. A ledger that began unsigned stays unsigned, because a signature would vouch for history nobody signed. A signed ledger refuses unsigned appends.

A signature cannot stop a rollback. Every head the key ever signed stays valid for its prefix of the ledger, so someone who can write the files could truncate the ledger and restore an older signed head, removing later failures. Keep the latest head where the ledger's writers cannot change it, for example as a CI artifact, and verify against it with `--head`.

## Verifying

```bash
medagentrx ledger verify ledger.jsonl
medagentrx ledger verify ledger.jsonl --head /trusted/copy/ledger.jsonl.head
medagentrx ledger verify ledger.jsonl --public-key keys/ledger-signing.pub --plan change-plan.yaml
medagentrx ledger show ledger.jsonl
```

`verify` exits with 0 when the chain and head agree, 1 when they do not, and 3 for an input or usage error. With `--public-key`, the head must also carry a valid signature from that key. With `--plan`, the key must be the one the plan pins. `check` refuses to use, or append to, a ledger that fails verification.

## Concurrency

`check` holds a lock file, `ledger.jsonl.lock`, from reading the budgets until the new entry is written. Two evaluations therefore cannot both spend the last look. An evaluation that read an older ledger is refused on append and must be run again. If a crash leaves the lock file behind, remove it once no evaluation is running.

<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# CI guides

Keep `ledger.jsonl` and `ledger.jsonl.head` between runs, for example committed to the repository or stored as a protected artifact. A fresh ledger on every run would reset the plan's budgets.

## GitHub Actions

```yaml
- uses: a7med7emedan/medagentrx@v0.2.0
  with:
    plan: change-plan.yaml
    candidate: predictions/candidate.parquet
    previous: predictions/previous.parquet
    anchor: predictions/anchor.parquet
    manifest: data/train_manifest.parquet
    model-meta: model.yaml
    ledger: governance/ledger.jsonl
    comment: "true"
```

The action runs the check in a read-only container without network, writes the summary to the job page, can comment on the pull request, uploads the HTML report as an artifact, and fails the job on FAILED or OUTSIDE_PLAN. Its outputs are `verdict` and `exit-code`. It needs a Linux runner with Docker.

## GitLab CI/CD

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/medagentrx/medagentrx@0.2.0
    inputs:
      image: <registry>/medagentrx@sha256:<digest>
      plan: change-plan.yaml
      candidate: predictions/candidate.parquet
      previous: predictions/previous.parquet
      anchor: predictions/anchor.parquet
      manifest: data/train_manifest.parquet
      model-meta: model.yaml
      ledger: governance/ledger.jsonl
```

The component publishes `junit.xml` as a test report, so each check appears in the merge request test widget, and keeps the reports and the ledger as artifacts.

## Notifications

`check` and `qc run` can post a one-line message to a Slack or Microsoft Teams webhook, or any HTTPS endpoint that takes JSON, when a verdict needs attention. Keep the URL in a secret named `MEDAGENTRX_NOTIFY_URL`. The message carries the verdict, plan, version and failed checks, never data. See [notifications](cli.md#notifications).

- **GitLab CI/CD.** Add `MEDAGENTRX_NOTIFY_URL` as a masked, protected CI/CD variable. The component's job reads it.
- **GitHub Actions.** The action runs its container with no network, so it never sends anything. Run MedAgentRx directly in the job when you want a message:

```yaml
- run: pip install medagentrx==0.2.0
- run: medagentrx qc run change-plan.yaml --scores qc/live-scores.parquet --expected qc/expected-2.0.0.parquet --model-version 2.0.0 --ledger governance/ledger.jsonl --out qc-report
  env:
    MEDAGENTRX_NOTIFY_URL: ${{ secrets.MEDAGENTRX_NOTIFY_URL }}
```

## Signing the ledger head

When the plan pins a key with `ledger_signing_key_sha256`, the run needs the private key. Keep it in a protected secret that model authors and agents cannot read. In GitHub Actions, pass it as `signing-key: ${{ secrets.MEDAGENTRX_SIGNING_KEY }}`, and `signing-key-passphrase` if the key is encrypted. The action writes it to a private temporary file, mounts it read-only into the container and removes it afterwards. In GitLab, store the key as a protected variable of type File named `MEDAGENTRX_SIGNING_KEY`. GitLab then exposes its path, which `check` reads. See [the decision ledger](ledger.md#signed-heads).

## pre-commit

```yaml
- repo: https://github.com/a7med7emedan/medagentrx
  rev: v0.2.0
  hooks:
    - id: medagentrx-validate
```

The hook validates every `change-plan*.yaml` before it is committed.

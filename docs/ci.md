<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# CI guides

Keep `ledger.jsonl` and `ledger.jsonl.head` between runs, for example committed to the repository or stored as a protected artifact. A fresh ledger on every run would reset the plan's budgets.

## GitHub Actions

```yaml
- uses: a7med7emedan/medagentrx@main  # pin to a commit SHA or, after the first release, a tag
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
  - component: $CI_SERVER_FQDN/<group>/medagentrx/medagentrx@main
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

## Signing the ledger head

When the plan pins a key with `ledger_signing_key_sha256`, the run needs the private key. Keep it in a protected secret that model authors and agents cannot read. In GitHub Actions, pass it as `signing-key: ${{ secrets.MEDAGENTRX_SIGNING_KEY }}`, and `signing-key-passphrase` if the key is encrypted. The action writes it to a private temporary file, mounts it read-only into the container and removes it afterwards. In GitLab, store the key as a protected variable of type File named `MEDAGENTRX_SIGNING_KEY`. GitLab then exposes its path, which `check` reads. See [the decision ledger](ledger.md#signed-heads).

## pre-commit

```yaml
- repo: https://github.com/a7med7emedan/medagentrx
  rev: main  # pin to a commit SHA or, after the first release, a tag
  hooks:
    - id: medagentrx-validate
```

The hook validates every `change-plan*.yaml` before it is committed.

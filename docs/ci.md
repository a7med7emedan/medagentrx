<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# CI guides

Keep `ledger.jsonl` and `ledger.jsonl.head` between runs, for example committed to the repository or stored as a protected artifact. A fresh ledger on every run would reset the plan's budgets.

## GitHub Actions

```yaml
- uses: a7med7emedan/medagentrx@v0.1.0
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
  - component: $CI_SERVER_FQDN/<group>/medagentrx/medagentrx@0.1.0
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

## pre-commit

```yaml
- repo: https://github.com/a7med7emedan/medagentrx
  rev: v0.1.0
  hooks:
    - id: medagentrx-validate
```

The hook validates every `change-plan*.yaml` before it is committed.

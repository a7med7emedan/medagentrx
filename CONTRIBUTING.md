<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Contributing

Thank you for helping. MedAgentRx guards decisions about clinical software, so changes are held to a high standard of evidence.

## Set up

```bash
uv sync
uv run pre-commit install
```

## Before opening a pull request

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run reuse lint
```

- Every new statistic needs a test against an independent reference or a known result, and a line in `docs/methods.md` with its source.
- Every new check needs an identifier, a family, a regulatory cross-reference and tests that make it pass, fail and, where relevant, warn.
- Run `uv run python scripts/make_docs.py` when the plan schema or the checks change, and commit the result.
- Never commit real patient data. Tests and examples use the synthetic demo only.

## Style

Write plain British English in short sentences, without em or en dashes. Commit messages have a short imperative subject line, a blank line, then why the change is needed.

## Changes to the plan format

The change-plan format is versioned by `pccp_version`. See [GOVERNANCE.md](GOVERNANCE.md) for how changes to it are decided.

By contributing you agree that your contribution is licensed under Apache-2.0.

<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Changelog

All notable changes are recorded here. The format follows Keep a Changelog, and the project uses semantic versioning.

## Unreleased

### Added

- Package scaffold, licensing, linting and continuous integration skeleton.
- Change-plan model with JSON Schema, hardened YAML loader, and the `validate`, `schema` and `init` commands.
- Example plan for a synthetic sepsis risk score.
- CSV and Parquet loaders for predictions, training manifest and model metadata, with size limits and path guards.
- Canonical locked test-set fingerprint and the `fingerprint` command.
- Statistics core: DeLong AUROC tests (cross-checked against R pROC), paired stratified bootstrap with BCa intervals, Tango paired proportions, calibration, net benefit, Holm and Bonferroni, alpha spending, power and standardised mean differences.
- Check registry with the 18 PLAN, DATA, PERF, LIFE and DOC checks, the evaluation engine and the verdict rule.
- Hash-chained decision ledger with a head file, budgets read back from it, `ledger verify` and `ledger show`, and the `check` command writing `report.json`.
- Synthetic sepsis demo cohort, nine planted scenarios with exact expected verdicts, the `demo` command, and example data in `examples/sepsis-risk`.

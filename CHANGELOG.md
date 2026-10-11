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

<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Changelog

All notable changes are recorded here. The format follows Keep a Changelog, and the project uses semantic versioning.

## 0.2.0, 2026-10-26

### Added

- Deployment QC: control samples for the live system, as in a clinical laboratory. A new library, runtime, hardware type or preprocessing step can change a deployed model's behaviour without changing its weights. The live system scores a locked set of raw control records on a schedule, and each run is IN_CONTROL (exit 0) or OUTSIDE_PLAN (exit 2).
- An optional `deployment_qc` plan block: fingerprints of the raw control inputs and their ids, the expected scores of each version known at authorisation, a per-record tolerance and the multirule QC rules. Plans without it validate and fingerprint exactly as before.
- The LIVE check family: the live version is the released one (LIVE-001), the score files are bound to the control set (LIVE-002), every record is within tolerance (LIVE-003), and the run bias passes the Westgard multirule rules 1_2s, 1_3s, 2_2s, R_4s and 10_x over the version's run history (LIVE-004).
- `medagentrx qc init` and `medagentrx qc run`, `medagentrx.qc` in the Python API and `Guard.qc` for agents. QC runs are a new `qc` entry kind in the same hash-chained ledger and never touch the locked test set.
- `medagentrx ledger release --qc-expected` records a later version's expected QC scores with its release, so a routine release never changes the plan.
- QC reports in HTML, JSON with a published schema, Markdown and JUnit, with a Levey-Jennings chart. The dashboard gains a QC page and lists QC runs in the timeline. The PCCP document gains a deployment QC section.
- A `mode: qc` input for the GitHub Action and the GitLab component; `check` stays the default.
- Eight planted QC scenarios in `medagentrx demo`, QC files and a scheduled workflow in the example, and a simulation of false alarms and detection in the validation results.
- `medagentrx preflight` checks an update's input files and the budgets left without evaluating it, so a mistake never costs a look at the locked test set.
- `medagentrx explain` prints what a check enforces, or lists every check.
- `medagentrx plan-diff` shows what changed between two plans, key by key.
- `medagentrx bundle create` writes an evidence bundle: the plan and its PCCP document, the ledger and the reports in one zip, with a manifest of SHA-256 hashes. `medagentrx bundle verify` checks a received bundle.
- `medagentrx ledger export` writes every ledger entry as a CSV or JSON table, quoting text a spreadsheet would run as a formula.
- `--json` output for `check`, `qc run`, `preflight`, `validate`, `plan-diff`, `explain` and `bundle verify`.
- Notifications: `check` and `qc run` post a short message to a Slack, Microsoft Teams or JSON webhook when a verdict needs attention, with `--notify` or `MEDAGENTRX_NOTIFY_URL`. It is off unless a URL is given, HTTPS only, and never carries data rows.
- Settings files: option defaults from `medagentrx.toml`, or `[tool.medagentrx]` in `pyproject.toml`, so a routine run is `medagentrx check`.
- Global options `--version`, `--quiet` and `--verbose`, and shell tab completion with `medagentrx --install-completion`.
- Documentation: a tutorial from plan to evidence, a glossary, a command-line reference generated from the parser, a Python API reference generated from the docstrings, and versioned documentation with a version menu. Links to the unversioned pages keep working.

### Changed

- The README opens with a figure of how the gate decides and shows the real output of a failing check. The terminal recording is removed, and the bio-creep timeline moves to the methods page.
- The regulatory mapping cites the FDA PCCP guidance as reissued on 18 August 2025 and maps deployment QC to post-market monitoring.

### Fixed

- The README's images and links are absolute, so they also work on the PyPI project page.
- The package metadata links the documentation and the changelog.
- Release notes are taken from this changelog.

## 0.1.0, 2026-10-14

First release.

### The gate

- Change plans as YAML with a published JSON Schema, parsed by a hardened loader: no anchors or aliases, no duplicate keys, JSON types only. `validate`, `schema`, `init` and `render-plan`, which writes the PCCP document from the same file.
- Nineteen checks in five families (PLAN, DATA, PERF, LIFE, DOC) and three verdicts, returned as the exit code.
- Prediction files are bound to the models that produced them (DATA-006), and the locked test set to its canonical fingerprint (DATA-001).
- Inclusion criteria are evaluated column by column with numpy, about twelve times faster than row by row on a million-row manifest.

### Statistics

- Paired DeLong AUROC tests with a Student t reference for small samples, matching R pROC to 1e-8.
- Tango score intervals for sensitivity and specificity, calibration slope and intercept, net benefit with paired stratified bootstrap intervals.
- Subgroup non-inferiority as an intersection-union test, with Holm and Bonferroni as stricter options.
- Bonferroni and alpha-investing spending across the life of the plan, and a cumulative check against the authorised version.
- `sample-size`, which sizes the locked test set for the plan's margin, level and power.
- A simulation suite for type I error, power and coverage, run nightly.

### Ledger

- Hash-chained, append-only, with a head file, a lock and refusal of stale evaluations. The plan's budgets are read back from it.
- Optional Ed25519 signatures on the head, with the key pinned in the plan (`ledger keygen`, `check --signing-key`, `ledger verify --public-key`).
- Entries may not run backwards in time, so the frequency limit cannot be dodged by setting the clock back.
- `card` and `release` records separate an acceptance from the model card update and from deployment. DOC-001 fails an update while the previous version's card is not recorded.

### Agents

- `Guard` limits an agent to the plan's automatic modifications and spends a test-set look per try.
- Thresholdout mode answers one noisy bit for all statistical criteria together. With the agent's validation predictions it follows Thresholdout (Dwork et al. 2015). The ledger records what the agent was told.

### Reports and integrations

- Self-contained HTML with inline figures, JSON with a published schema, a Markdown summary and JUnit XML. A read-only local dashboard (`[web]` extra).
- A synthetic sepsis demo with ten planted scenarios. Versions are recalibrated on a separate development sample, not on the locked test set.
- A GitHub Action, a GitLab CI/CD component, a pre-commit hook, and a non-root, read-only container image.
- CodeQL, OpenSSF Scorecard, pip-audit and gitleaks in CI. A release workflow that publishes to PyPI by trusted publishing and ships a cosign-signed image, CycloneDX SBOMs and build provenance.

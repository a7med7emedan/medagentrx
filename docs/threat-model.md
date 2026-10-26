<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Threat model

MedAgentRx reads files that people and agents control, and its verdict decides whether a clinical model update may be released. This page lists what it defends against, using STRIDE: spoofing, tampering, repudiation, information disclosure, denial of service and elevation of privilege.

## Assets

- The **verdict** and the decision it supports.
- The **decision ledger**, which holds the plan's budgets: test-set looks, alpha and accepted updates.
- The **locked test set**, whose value depends on limited use.
- The **reader** of reports and the dashboard.

## Threats and mitigations

| Threat | STRIDE | Mitigation | Where |
|---|---|---|---|
| Malicious plan file runs code through YAML tags | Elevation of privilege | Hardened `SafeLoader`: no Python tags, no aliases, no duplicate keys; JSON Schema and pydantic validation with unknown keys refused | `safe_yaml.py`, `plan/` |
| Plan file exhausts memory (billion laughs, huge file, deep nesting) | Denial of service | Anchors and aliases refused; byte limit before parsing; nesting depth caught | `safe_yaml.py`, `io/text.py` |
| Malicious prediction or model file runs code when loaded | Elevation of privilege | Predictions only, as CSV or Parquet; model binaries, pickles and joblib files are never opened; no `eval` or `exec` | `io/` |
| Oversized or malformed prediction file | Denial of service | Byte and row limits checked before reading (Parquet from its footer); nested types, NaN, out-of-range scores and duplicate ids refused | `io/tables.py`, `io/predictions.py` |
| Symlink in a checkout points at secrets outside it | Information disclosure | Inside the working directory, symlinks are followed only when they stay inside it | `io/paths.py` |
| Output written outside the output folder | Tampering | Output names checked; absolute paths, `..` and symlinked targets refused | `io/paths.py` |
| Script injection through plan text, labels or data into reports | Tampering, information disclosure | Jinja2 autoescaping; no script in reports; figures drawn as paths with no external reference; CSP that forbids loading anything | `report/` |
| Edited, reordered or removed ledger entries hide failed attempts | Tampering, repudiation | Hash chain over every entry, a head file and an optional Ed25519 signature on the head, pinned by the plan; `check` refuses a ledger that fails verification. A trusted copy of the latest head detects rollback | `ledger.py`, `signing.py` |
| Two evaluations race for the last test-set look | Tampering | A lock spans reading budgets to appending; stale evaluations refused | `ledger.py` |
| Clock set back to slip past the frequency limit | Tampering | Entries must not run backwards in time; `check` refuses an earlier time and `verify` reports one | `ledger.py` |
| An agent fits the locked test set by trying many candidates | Information disclosure | Look budget counts every try; thresholdout mode returns one noisy bit; only automatic modifications allowed | `guard.py` |
| Changed test labels or a different test set | Tampering | Canonical test-set fingerprint pinned in the plan (DATA-001) | `io/fingerprint.py` |
| Live stack changed without a declared update (library, runtime, hardware, preprocessing, or an unreleased version) | Tampering | Deployment QC: control records scored by the live system on a schedule, checked by version, binding, per-record tolerance and multirule QC (LIVE-001 to LIVE-004) | `qc.py`, `checks/live_checks.py` |
| Plan changed without a new revision | Tampering, repudiation | Plan fingerprint recorded in the ledger and compared (PLAN-001) | `checks/plan_checks.py` |
| Webhook URL leaks, or the notification is sent somewhere else | Information disclosure | Notifications are off unless a URL is given; HTTPS only; redirects refused; the URL is never printed, reported or recorded; the message carries no data rows | `notify.py` |
| Settings file sets a dangerous default without notice | Tampering | Settings are read only from the current folder or a named file; unknown keys are refused; command-line options and environment variables win | `settings.py` |
| Evidence bundle altered after it was made, or a crafted zip attacks the reviewer | Tampering, denial of service | Manifest of SHA-256 hashes checked file by file; ledger chain recomputed; unsafe names, oversized members and unlisted files refused; nothing extracted except the ledger, into a temporary folder | `bundle.py` |
| Exported ledger runs a formula in a spreadsheet | Elevation of privilege | Text cells that start like a formula are quoted | `export.py` |
| Dashboard exposed to a network | Information disclosure | Read-only GET routes, no cookies, strict security headers; binds to 127.0.0.1 and warns loudly otherwise | `web/` |
| Compromised dependency or image | Tampering | Locked dependencies; pip-audit, CodeQL, Trivy and OpenSSF Scorecard in CI; base images pinned by digest; image signed and shipped with an SBOM and provenance | CI, `Dockerfile` |

## Residual risks

- Without a signing key, whoever controls both the ledger and its head file can rewrite history. Pin a signing key in the plan, or keep a copy of the head where the ledger's writers cannot change it.
- A clock set forward is not detected when it happens. Later entries made with the correct time are then refused, which shows the problem, but the frequency limit was already measured from the wrong time. Run checks on a host with a trusted, synchronised clock.
- A signed head does not prevent rollback. Truncating the ledger and restoring an older signed head passes verification unless the verifier holds a newer head. Keep the latest head outside the writers' reach, or anchor it in a transparency log (see the roadmap).
- Whoever holds the signing key can sign a rewritten head. Keep the key with a party that does not train or submit models, such as a protected CI secret.
- The tool trusts that prediction files come from the models they claim to. Model provenance is the quality system's job.
- In thresholdout mode each look still leaks a little information. The look budget bounds the total.
- An evidence bundle proves its files match its own manifest, not who made it. Send the ledger's public key, or the plan that pins it, by a separate channel, and check the bundle with `--public-key`.
- Deployment QC trusts that the live score file came from the live system. A scheduler that replays an old score file would hide a change. Run the QC job where the people who change the deployment cannot alter its output, and compare the score file's SHA-256 across runs: a noisy stack never produces the same file twice.

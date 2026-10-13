<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Threat model

MedAgentRx reads files that people and agents control, and its verdict can release a clinical model. This page lists what it defends against, using STRIDE: spoofing, tampering, repudiation, information disclosure, denial of service and elevation of privilege.

## Assets

- The **verdict** and the decision it supports.
- The **decision ledger**, which holds the plan's budgets: test-set looks, alpha and releases.
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
| Edited, reordered or removed ledger entries hide failed attempts | Tampering, repudiation | Hash chain over every entry, a head file and an optional Ed25519 signature on the head, pinned by the plan; `check` refuses a ledger that fails verification | `ledger.py`, `signing.py` |
| Two evaluations race for the last test-set look | Tampering | A lock spans reading budgets to appending; stale evaluations refused | `ledger.py` |
| Clock set back to slip past the frequency limit | Tampering | Entries must not run backwards in time; `check` refuses an earlier time and `verify` reports one | `ledger.py` |
| An agent fits the locked test set by trying many candidates | Information disclosure | Look budget counts every try; thresholdout mode returns one noisy bit; only automatic modifications allowed | `guard.py` |
| Changed test labels or a different test set | Tampering | Canonical test-set fingerprint pinned in the plan (DATA-001) | `io/fingerprint.py` |
| Plan changed without a new revision | Tampering, repudiation | Plan fingerprint recorded in the ledger and compared (PLAN-001) | `checks/plan_checks.py` |
| Dashboard exposed to a network | Information disclosure | Read-only GET routes, no cookies, strict security headers; binds to 127.0.0.1 and warns loudly otherwise | `web/` |
| Compromised dependency or image | Tampering | Locked dependencies; pip-audit, CodeQL, Trivy and OpenSSF Scorecard in CI; base images pinned by digest; image signed and shipped with an SBOM and provenance | CI, `Dockerfile` |

## Residual risks

- Without a signing key, whoever controls both the ledger and its head file can rewrite history. Pin a signing key in the plan, or keep a copy of the head where the ledger's writers cannot change it.
- A clock set forward is not detected when it happens. Later entries made with the correct time are then refused, which shows the problem, but the frequency limit was already measured from the wrong time. Run checks on a host with a trusted, synchronised clock.
- Whoever holds the signing key can sign a rewritten head. Keep the key with a party that does not train or submit models, such as a protected CI secret.
- The tool trusts that prediction files come from the models they claim to. Model provenance is the quality system's job.
- In thresholdout mode each look still leaks a little information. The look budget bounds the total.

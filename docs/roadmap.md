<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Roadmap

Planned after version 0.1:

- **Deployment QC (control samples).** A clinical lab runs a control sample with a known answer on a schedule, and stops when the result drifts. MedAgentRx will do the same for the live model, which scores a locked set of raw control records on a schedule. A shift with no listed modification behind it is an undeclared update, even when the weights are unchanged.
- Multiclass, survival (C-index, time-dependent AUC), regression and segmentation models.
- Running model binaries as ONNX in a sandbox, as an alternative to prediction files.
- DOCX export of the PCCP document.
- MLflow and DVC integrations.
- Connectors for real-world performance monitoring.
- Anchoring signed ledger heads in a public transparency log, such as Sigstore Rekor.

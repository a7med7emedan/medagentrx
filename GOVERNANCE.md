<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Governance

## Maintainer

MedAgentRx is maintained by Ahmed Hemedan, who decides on releases, the roadmap and changes to the plan format.

## How decisions are made

Proposals start as an issue. Changes that affect statistics, checks or the plan format need an issue describing the change, its evidence and its effect on existing plans before a pull request is merged.

## Versioning of the change-plan format

- `pccp_version` names the format of `change-plan.yaml`. The current format is `"1.0"`.
- Adding an optional key with a default that keeps existing plans' behaviour is a minor change within the same format version.
- Renaming or removing a key, changing a default, or changing how a check decides is a breaking change. It needs a new `pccp_version`, a migration note, and support for the previous version for at least one minor release.
- The JSON Schema in `schema/` is regenerated and published with every release.

## Versioning of the package

The package follows semantic versioning. The report format is versioned separately by `report_schema` in `report.json`.

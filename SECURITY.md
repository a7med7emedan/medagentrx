<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button on the repository's Security tab (private vulnerability reporting). Do not open a public issue.

Include the version, a description, steps to reproduce and the impact you expect. Synthetic inputs are best; never send real patient data.

## What to expect

- Acknowledgement within 5 working days.
- A first assessment within 10 working days.
- A fix or a mitigation for confirmed HIGH or CRITICAL issues as soon as practical, normally within 30 days, followed by a release and an advisory.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| Earlier development versions | No |

## Scope

In scope: the `medagentrx` package, its command line, the container image, the GitHub Action, the GitLab component and the dashboard. The [threat model](docs/threat-model.md) lists the threats MedAgentRx is designed against.

Out of scope: exposing the dashboard beyond 127.0.0.1 (it has no authentication by design), and findings in third-party dependencies that are not reachable through MedAgentRx.

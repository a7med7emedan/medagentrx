<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# MedAgentRx

**The prescription for self-improving medical AI.** Every model update, by an engineer, a pipeline or an AI agent, is checked against its approved change plan (FDA PCCP, EU AI Act Art. 43(4)).

AI agents and automated pipelines now retrain clinical models on their own. MedAgentRx lets them change a model only as the approved plan prescribes. The plan is one YAML file. Each update is checked against it and receives one verdict:

| Verdict | Meaning |
|---|---|
| `ACCEPTED` | Inside the plan and every criterion met. |
| `FAILED` | Inside the plan, but a criterion was not met. Do not release. |
| `OUTSIDE_PLAN` | The change is not covered by the plan. It needs a new submission. |

Every evaluation is recorded in a tamper-evident ledger, including failed ones. A person or an agent therefore cannot keep trying candidates until one passes by chance.

> **Status:** early development. The interface is not yet stable.

## Disclaimer

MedAgentRx supports a quality management system. It is not legal or regulatory advice, does not replace your QMS or regulatory strategy, and its output is not itself a regulatory submission.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Author

Ahmed Hemedan.

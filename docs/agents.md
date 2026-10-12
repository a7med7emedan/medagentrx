<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# For agents and AutoML

AutoML loops and coding agents now retrain clinical models on their own. MedAgentRx makes the approved plan the leash: an agent may change the model only as the plan prescribes, with a capped number of looks at the locked test set.

## The guard

```python
from medagentrx.guard import Guard

g = Guard(
    plan="change-plan.yaml", ledger="ledger.jsonl", mode="thresholdout", previous="previous.parquet"
)
print([m.id for m in g.allowed_modifications()])
decision = g.submit(
    candidate="cand.parquet", model_meta="model.yaml", manifest="train_manifest.parquet"
)
decision.allowed  # True or False
decision.reason  # short text, no test-set metrics in thresholdout mode
decision.looks_remaining  # looks left under the plan
```

- **What the agent may try.** `allowed_modifications()` lists the plan's modifications with `automatic: true`. Any other modification is refused before any data is read, and it spends no look.
- **Every look counts.** Each submission that reaches the data spends one look from `max_evaluations` and is written to the ledger, whether it passes or not. When the budget is used up, the guard refuses with DATA-004 and the update is outside the plan.
- **No alpha, no release.** Guard looks spend no alpha and never count as released updates. A candidate the agent prefers still needs a formal `medagentrx check`, which records the release decision.

## Thresholdout mode

Each look tells the agent one bit. Following the reusable holdout of Dwork et al. (2015), Laplace noise (scale 1 standard error by default) is added to the margin of the primary AUROC test before it is compared with zero. No metric is returned.

The other statistical criteria answer exactly, so each adds at most one bit. Use `mode="exact"` for supervised use, where the verdict and failed checks are returned.

The ledger keeps the exact outcome of every look for auditors. In thresholdout mode, keep the ledger and the noise seed where the agent cannot read them.

## Example

`examples/agent_loop.py` runs a small search loop on synthetic data. It stops when the guard refuses:

```bash
uv run python examples/agent_loop.py --out agent-demo
```

The `peeking-agent` scenario of `medagentrx demo` asserts the same behaviour: 25 submissions on a budget of 20 looks give 20 answers, then OUTSIDE_PLAN through DATA-004.

## References

- Dwork C., Feldman V., Hardt M., Pitassi T., Reingold O., Roth A. Generalization in adaptive data analysis and holdout reuse. NeurIPS 2015.

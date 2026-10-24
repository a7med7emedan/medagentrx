<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# For agents and AutoML

AutoML loops and coding agents can now retrain a clinical model without a person in the loop. With MedAgentRx, an agent may change the model only in the ways the plan marks as automatic, and only within a fixed number of looks at the locked test set.

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
- **No alpha, no release.** Guard looks spend no alpha and never count as released updates. A candidate the agent prefers still needs a formal `medagentrx check` before it can be accepted.

An agent that operates the deployment can also run [deployment QC](qc.md) through the guard. `g.qc(scores, expected, model_version="2.0.0")` judges a run of the live system and records it in the same ledger. QC never touches the locked test set, so its exact result is returned.

## Thresholdout mode

Each look tells the agent one bit about the plan's statistical criteria taken together. The guard puts every criterion that reads the test-set labels on one scale: the estimate's distance beyond its boundary, in standard errors, minus the critical value. A criterion passes exactly when this slack is positive. The guard takes the smallest slack across the plan, adds Laplace noise once, and answers whether the result is above zero. No metric is returned.

Pass the agent's own validation data to go further:

```python
from medagentrx.guard import Validation

decision = g.submit(
    candidate="cand.parquet",
    model_meta="model.yaml",
    manifest="train_manifest.parquet",
    validation=Validation(candidate="val_cand.parquet", previous="val_prev.parquet"),
)
```

The guard then runs Thresholdout (Dwork et al. 2015). It computes the same slack on the validation data, using the test set's standard errors so the two are on one scale. If the two agree within a noisy threshold, the answer comes from the validation data and reveals almost nothing about the test set. If they disagree, the noisy test-set answer is given and the threshold noise is drawn again. The noise scale is 0.5 standard errors by default, and the threshold is four times the noise scale, as in the worked example of Dwork et al.

Every look still counts against `max_evaluations`, whichever source answered. The budget is a limit the regulator agreed to, so the guard does not relax it.

Failures that do not depend on test-set labels, such as a model card that cannot be completed, are reported exactly. Use `mode="exact"` for supervised use, where the verdict and failed checks are returned.

The ledger keeps the exact outcome of every look and, under `answer`, what the agent was told and from which source. In thresholdout mode, keep the ledger and the noise seed where the agent cannot read them.

## Example

`examples/agent_loop.py` runs a small search loop on synthetic data. It stops when the guard refuses:

```bash
uv run python examples/agent_loop.py --out agent-demo
```

The `peeking-agent` scenario of `medagentrx demo` asserts the same behaviour: 25 submissions on a budget of 20 looks give 20 answers, then OUTSIDE_PLAN through DATA-004.

## References

- Dwork C., Feldman V., Hardt M., Pitassi T., Reingold O., Roth A. Generalization in adaptive data analysis and holdout reuse. NeurIPS 2015.

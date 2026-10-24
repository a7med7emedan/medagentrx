<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# FAQ

**Does MedAgentRx load my model?**
No. It reads predictions only, as Parquet or CSV. Model files such as pickles can run arbitrary code when loaded, so they are never opened.

**Which models are supported?**
Version 0.1 covers binary classification risk models, the most common kind of clinical prediction model. Multiclass, survival, regression and segmentation are on the roadmap.

**Why does a failed evaluation count against the budget?**
The locked test set loses its value if it is used to pick among many candidates. Counting every look, including failures, stops a person or an agent from trying until one passes by chance.

**What is bio-creep?**
A series of updates, each only slightly worse than the one before, can drift a long way from the authorised model. LIFE-001 compares every update with the anchor as well as with its predecessor.

**Can an agent use MedAgentRx directly?**
Yes. The [guard](agents.md) lets an agent try only the modifications the plan marks automatic and spends a look per try. In thresholdout mode it answers with one noisy bit for the whole plan, and with the agent's own validation data it runs Thresholdout.

**Does MedAgentRx notice dependency, runtime or preprocessing changes?**
Yes, with [deployment QC](qc.md). Such a change can move a model's scores without changing its weights, so update checks alone would miss it. The live system scores a locked set of raw control records on a schedule, and every run is compared with the released version's expected scores. Gross changes fail the per-record tolerance (LIVE-003); small systematic ones fail the multirule rules (LIVE-004). A version running live that was never released fails LIVE-001.

**Is the output a regulatory submission?**
No. MedAgentRx supports a quality management system. Its reports are evidence for that system, not a submission.

**Why is the dashboard read-only and local?**
It has no authentication in version 0.1. It binds to 127.0.0.1 by default and warns loudly if bound elsewhere.

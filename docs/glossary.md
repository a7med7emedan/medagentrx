<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Glossary

Plain explanations of the terms these pages use, for readers from regulatory, clinical, quality and engineering backgrounds.

**Alpha.** The chance a statistical test accepts a worse model by bad luck. The plan sets a total alpha for its whole life, and each update spends part of it. When it is spent, no more updates can be tested under the plan.

**Anchor version.** The model version that was originally authorised. Every update is compared with it as well as with the version it replaces, so many small losses cannot add up unnoticed.

**AUROC.** Area under the ROC curve: how well a risk score ranks patients who have the outcome above those who do not. 0.5 is chance and 1.0 is perfect.

**Bio-creep.** Slow decline across many updates, each only slightly worse than the one before. Comparing every update with the anchor version catches it.

**Calibration.** Whether predicted risks match observed rates. A well-calibrated model that says 20% is right about one time in five.

**Change plan.** The approved description of which changes a model may undergo and how each is tested. In MedAgentRx it is the file `change-plan.yaml`. See PCCP.

**Check.** One rule MedAgentRx applies, with an identifier such as PERF-001. The [checks catalogue](checks.md) lists them all, and `medagentrx explain` prints any one.

**Control set.** A small, fixed set of raw input records with known expected scores, used by deployment QC. Like a control sample in a clinical laboratory.

**Decision ledger.** The file `ledger.jsonl`, where every check, release and QC run is recorded. Each entry includes a hash of the one before, so any change to the history is detected.

**DeLong test.** A standard statistical method for comparing the AUROC of two models on the same patients.

**Deployment QC.** Scheduled checks that the live system still gives the released version's scores on the control set. It catches changes nobody declared, such as a library upgrade. See [Deployment QC](qc.md).

**Evidence bundle.** One zip file with the plan, the ledger and the reports, plus a manifest of SHA-256 hashes, for a reviewer or auditor. Made with `medagentrx bundle create`.

**Exit code.** The number a command returns when it finishes. CI systems read it to decide whether a job passed. MedAgentRx's exit code is its verdict.

**Fingerprint.** A SHA-256 hash that identifies a file or data set. The plan pins the fingerprint of the locked test set, so any change to it is detected.

**Hash, SHA-256.** A 64-character code computed from a file's exact contents. Changing one byte changes the hash completely.

**Intended use.** The statement of what the model is for and for whom. The plan pins its hash, and an update may not change it.

**Levey-Jennings chart.** A laboratory chart of control results over time, with lines at one, two and three standard deviations. Deployment QC reports draw one.

**Locked test set.** Patient records set aside to judge every update, never used for training. Each evaluation is a look, and the plan limits the number of looks.

**Look.** One evaluation on the locked test set. Repeated looks let a model be fitted to the test set by chance, so the plan limits them.

**Manifest.** A table with one row per training record, used to check that training data meets the plan's inclusion rules and does not overlap the test set.

**Modification.** A kind of change the plan allows, such as retraining the same architecture. Each update names the modification it applies.

**Net benefit.** A measure of clinical value at a decision threshold, weighing true positives against false positives as a clinician would.

**Non-inferiority.** A test that the new model is not worse than the old one by more than a set margin.

**Notified body.** An organisation designated in the European Union to assess medical devices against the regulations.

**OUTSIDE_PLAN.** The verdict for an update the plan does not cover. It cannot be released under the plan, and a new regulatory submission is needed.

**PCCP.** Predetermined Change Control Plan: the FDA's name for an approved change plan for an AI-enabled medical device. The EU AI Act Article 43(4) has the same idea.

**Preflight.** A check of an update's input files before the real check. It computes nothing on the test set and spends no look.

**Subgroup.** A group of patients defined by a characteristic such as sex, age band or site. The plan can require that no subgroup is harmed by an update.

**Thresholdout.** A method that lets an AI agent learn whether its candidate passes while revealing very little about the test set.

**Verdict.** The single outcome of a check: ACCEPTED, FAILED or OUTSIDE_PLAN for an update, and IN_CONTROL or OUTSIDE_PLAN for a deployment QC run.

**Westgard rules.** Laboratory rules for deciding when control results show a real change rather than noise. Deployment QC applies them to the live system.

**YAML.** A plain-text format for structured settings, readable by people. The change plan is written in it.

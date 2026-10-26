<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

<!-- This page is written by scripts/make_docs.py. Edit the code, not this file. -->

# Python API reference

The functions and classes below are the stable Python interface. Everything the command line does is available here, with the same inputs and outputs. Import from `medagentrx` unless a different module is shown.

## Checking updates

### check

```python
check(
    *,
    plan: str | Path,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    manifest: str | Path,
    model_meta: str | Path,
    ledger: str | Path,
    out: str | Path,
    seed: int = 0,
    n_replicates: int = 2000,
    formats: Iterable[str] = ('html', 'json', 'md', 'junit'),
    limits: Limits | None = None,
    signing_key: str | Path | None = None,
)
```

Check one update against its plan, record it in the ledger and write reports.

The ledger is locked from reading its budgets until the new entry is
written. An invalid plan gives OUTSIDE_PLAN and is not recorded. When the
plan names a ledger signing key, ``signing_key`` must be that private key;
the existing head is verified with it and the new head is signed.

**Raises**

- InputError: If an input file other than the plan is missing or invalid.
- LedgerError: If the ledger fails verification.

### CheckResult

```python
CheckResult(
    evaluation: Evaluation,
    ledger_entry: dict[str, Any] | None,
    reports: dict[str, Path] = {},
)
```

Outcome of ``check``.

**Attributes**

| Name | Description |
|---|---|
| `evaluation` | Every finding and number behind the verdict. |
| `ledger_entry` | The entry written to the ledger, or None for an invalid plan. |
| `reports` | Written report files by format. |

### Verdict

*enumeration*: `ACCEPTED`, `FAILED`, `OUTSIDE_PLAN`.

The single outcome of an evaluation.

- `exit_code` (property): Process exit code for this verdict.

## Deployment QC

### qc

```python
qc(
    *,
    plan: str | Path,
    scores: str | Path,
    expected: str | Path,
    model_version: str,
    ledger: str | Path,
    out: str | Path,
    control_inputs: str | Path | None = None,
    formats: Iterable[str] = ('html', 'json', 'md', 'junit'),
    limits: Limits | None = None,
    signing_key: str | Path | None = None,
)
```

Run deployment QC on the live system's control scores, record it and write reports.

The live system scores the plan's locked control set; ``scores`` is that
file and ``expected`` the expected scores of ``model_version``. The run
history and the released version are read from the ledger, which is locked
until the QC entry is written.

**Raises**

- PlanError: If the plan is invalid.
- InputError: If the plan has no QC block or an input file is invalid.
- LedgerError: If the ledger fails verification.

### QcResult

```python
QcResult(run: QcRun, ledger_entry: dict[str, Any], reports: dict[str, Path] = {})
```

Outcome of ``qc``.

**Attributes**

| Name | Description |
|---|---|
| `run` | Every finding and number behind the QC verdict. |
| `ledger_entry` | The QC entry written to the ledger. |
| `reports` | Written report files by format. |

### QcVerdict

*enumeration*: `IN_CONTROL`, `OUTSIDE_PLAN`.

The outcome of a QC run.

- `exit_code` (property): 0 for IN_CONTROL, 2 for OUTSIDE_PLAN.

## Agents and AutoML

### guard.Guard

```python
Guard(
    plan: str | Path,
    ledger: str | Path,
    mode: Mode = 'thresholdout',
    *,
    previous: str | Path,
    anchor: str | Path | None = None,
    noise_scale: float = 0.5,
    threshold: float | None = None,
    seed: int | None = None,
    n_replicates: int = 2000,
    signing_key: str | Path | None = None,
)
```

Gate an agent's candidates against the approved change plan.

**Args**

| Name | Description |
|---|---|
| `plan` | ``change-plan.yaml``. |
| `ledger` | Decision ledger shared with formal checks. |
| `mode` | ``thresholdout`` (default) or ``exact``. |
| `previous` | Predictions of the deployed version on the locked test set. |
| `anchor` | Predictions of the authorised version. Defaults to ``previous``. |
| `noise_scale` | Laplace scale for thresholdout answers, in standard error units. |
| `threshold` | Thresholdout threshold on the validation and test-set gap. Defaults to four times ``noise_scale``. |
| `seed` | Seed of the noise. Defaults to a fresh random seed, which the agent should not know. |
| `n_replicates` | Bootstrap replicates for each look. |
| `signing_key` | Ledger signing key, required when the plan names one. Run the guard in a process the agent cannot read when using it. |

#### Guard.allowed_modifications

```python
allowed_modifications()
```

Modifications the plan lets a pipeline or agent trigger without a person.

#### Guard.submit

```python
submit(
    candidate: str | Path,
    model_meta: str | Path,
    *,
    manifest: str | Path,
    validation: Validation | None = None,
    now: dt.datetime | None = None,
)
```

Evaluate one candidate, record the look and answer the agent.

**Args**

| Name | Description |
|---|---|
| `candidate` | Candidate predictions on the locked test set. |
| `model_meta` | ``model.yaml`` of the candidate. |
| `manifest` | Training data manifest of the candidate. |
| `validation` | Predictions on the agent's own validation data. In thresholdout mode they let the guard answer from them when they agree with the locked test set. |
| `now` | Evaluation time. Defaults to the current UTC time. |

#### Guard.qc

```python
qc(
    scores: str | Path,
    expected: str | Path,
    *,
    model_version: str,
    control_inputs: str | Path | None = None,
    now: dt.datetime | None = None,
)
```

Run deployment QC on the live system and record it in the guard's ledger.

An agent that operates the deployment can check, on a schedule, that the
live stack still reproduces the released version's control scores. The
exact QC result is returned; QC runs never touch the locked test set, so
nothing about it needs hiding.

**Args**

| Name | Description |
|---|---|
| `scores` | Live scores on the plan's control set. |
| `expected` | Expected scores of ``model_version`` on the control set. |
| `model_version` | Version the live system reports it is running. |
| `control_inputs` | The raw control file, to check it against the plan. |
| `now` | Time of the run. Defaults to the current UTC time. |

### guard.Decision

```python
Decision(
    allowed: bool,
    reason: str,
    looks_used: int,
    looks_remaining: int,
    verdict: Verdict | None = None,
    failed_checks: tuple[str, ...] = (),
)
```

What the guard tells the agent.

**Attributes**

| Name | Description |
|---|---|
| `allowed` | True when the candidate may go forward to a formal check. |
| `reason` | Short text without test-set metrics in thresholdout mode. |
| `looks_used` | Looks at the locked test set used so far, including this one. |
| `looks_remaining` | Looks still available under the plan. |
| `verdict` | Exact verdict in exact mode; None in thresholdout mode. |
| `failed_checks` | Failed checks in exact mode, or plan and data checks that refused the candidate in either mode. |

## Lower-level building blocks

### evaluate

```python
evaluate(
    *,
    plan: str | Path,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    manifest: str | Path,
    model_meta: str | Path,
    history: History | None = None,
    seed: int = 0,
    n_replicates: int = 2000,
    limits: Limits | None = None,
    now: dt.datetime | None = None,
    base: Path | None = None,
)
```

Evaluate one candidate update against its change plan.

**Args**

| Name | Description |
|---|---|
| `plan` | ``change-plan.yaml``. |
| `candidate` | Candidate predictions on the locked test set. |
| `previous` | Predictions of the version being replaced. |
| `anchor` | Predictions of the originally authorised version. |
| `manifest` | Training data manifest of the candidate. |
| `model_meta` | ``model.yaml`` of the candidate. |
| `history` | Budgets used so far, from the ledger. Empty if None. |
| `seed` | Seed for every resampling step. |
| `n_replicates` | Bootstrap replicates. |
| `limits` | Input size limits. |
| `now` | Evaluation time. Defaults to the current UTC time. |
| `base` | Directory input symlinks may point into. |

**Raises**

- InputError: If an input file other than the plan is missing or invalid.

### Evaluation

```python
Evaluation(
    verdict: Verdict,
    findings: tuple[Finding, ...],
    plan_id: str | None,
    plan_revision: int | None,
    plan_fingerprint: str | None,
    candidate_version: str | None,
    previous_version: str | None,
    modification_id: str | None,
    test_fingerprint: str | None,
    alpha_method: str | None,
    alpha_used: float | None,
    touched_test_set: bool,
    inputs: dict[str, str],
    seed: int,
    n_replicates: int,
    evaluated_at: dt.datetime,
    alpha_state: AlphaState | None = None,
    ledger_entries_before: int = 0,
    tool_version: str = '0.2.0',
    notes: tuple[str, ...] = (),
)
```

Everything decided about one candidate update.

**Attributes**

| Name | Description |
|---|---|
| `verdict` | ACCEPTED, FAILED or OUTSIDE_PLAN. |
| `findings` | One finding per check, in catalogue order. |
| `plan_id` | Plan identifier, or None if the plan was invalid. |
| `plan_revision` | Plan revision, or None if the plan was invalid. |
| `plan_fingerprint` | Plan fingerprint, or None if the plan was invalid. |
| `candidate_version` | Version of the candidate model. |
| `previous_version` | Version it replaces. |
| `modification_id` | Plan modification claimed. |
| `test_fingerprint` | Fingerprint of the candidate's test rows. |
| `alpha_method` | Alpha spending rule of the plan. |
| `alpha_used` | Level used for this evaluation, or None if no test ran. |
| `alpha_state` | Alpha accounting before this evaluation, or None if the plan was invalid. |
| `ledger_entries_before` | Ledger entries the budgets were read from. |
| `touched_test_set` | Whether the locked test set was evaluated. |
| `inputs` | SHA-256 of every input file by role. |
| `seed` | Seed used for resampling. |
| `n_replicates` | Bootstrap replicates. |
| `evaluated_at` | Time of the evaluation. |
| `tool_version` | Version of this package. |

### QcRun

```python
QcRun(
    verdict: QcVerdict,
    findings: tuple[Finding, ...],
    plan_id: str,
    plan_revision: int,
    plan_fingerprint: str,
    model_version: str,
    released_version: str,
    inputs: dict[str, str],
    bias: float | None,
    max_abs_deviation: float | None,
    rejections: tuple[str, ...],
    warnings: tuple[str, ...],
    z: float | None,
    mean: float | None,
    sd: float | None,
    history: tuple[QcHistoryRun, ...],
    run_at: dt.datetime,
    ledger_entries_before: int = 0,
    tool_version: str = '0.2.0',
    notes: tuple[str, ...] = (),
)
```

Everything decided about one QC run.

**Attributes**

| Name | Description |
|---|---|
| `verdict` | IN_CONTROL or OUTSIDE_PLAN. |
| `findings` | One finding per LIVE check, in catalogue order. |
| `plan_id` | Plan identifier. |
| `plan_revision` | Plan revision. |
| `plan_fingerprint` | Plan fingerprint. |
| `model_version` | Version the live system reports. |
| `released_version` | Version the ledger says is released. |
| `inputs` | SHA-256 of every input file by role. |
| `bias` | Mean of live minus expected score, or None if not measured. |
| `max_abs_deviation` | Largest absolute difference, or None if not measured. |
| `rejections` | Multirule rules that rejected the run. |
| `warnings` | Multirule rules that warned. |
| `z` | Standardised bias, or None before the baseline is complete. |
| `mean` | Target bias of the multirule check, or None before the baseline. |
| `sd` | SD of the multirule check, or None before the baseline. |
| `history` | Earlier runs of this version, oldest first. |
| `run_at` | Time of the run. |
| `ledger_entries_before` | Ledger entries the history was read from. |
| `tool_version` | Version of this package. |

### load_plan

```python
load_plan(path: str | Path, *, max_bytes: int = 1000000)
```

Load and validate a change plan file.

**Args**

| Name | Description |
|---|---|
| `path` | Path to ``change-plan.yaml``. |
| `max_bytes` | Largest file size accepted. |

**Returns**

- The validated plan.

**Raises**

- PlanError: If the file cannot be read or the plan is not valid.

### ChangePlan

*class*, a validated pydantic model. Its keys are listed in the [change plan reference](plan-reference.md).

An approved change plan for one clinical prediction model.

### preflight.preflight

```python
preflight(
    *,
    plan: str | Path,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    manifest: str | Path,
    model_meta: str | Path,
    ledger: str | Path | None = None,
    public_key: Ed25519PublicKey | None = None,
    limits: Limits | None = None,
)
```

Check the inputs of one update without evaluating it.

Every problem is reported, not only the first. With ``public_key``, the
ledger head must carry a valid signature by that key.

### preflight.Preflight

```python
Preflight(items: tuple[Item, ...], warnings: tuple[str, ...] = ())
```

Outcome of ``preflight``.

**Attributes**

| Name | Description |
|---|---|
| `items` | Every step, in the order run. |
| `warnings` | Plan logic warnings, which never block the check. |

### plan.diff.diff_plans

```python
diff_plans(old: ChangePlan, new: ChangePlan)
```

Every difference between ``old`` and ``new``.

### bundle.create_bundle

```python
create_bundle(
    *,
    plan: str | Path,
    ledger: str | Path,
    out: str | Path,
    reports: tuple[str | Path, ...] = (),
    public_key_file: str | Path | None = None,
    now: dt.datetime | None = None,
)
```

Write an evidence bundle.

**Raises**

- PlanError: If the plan is not valid.
- BundleError: If the ledger fails verification or a file is too large.
- InputError: If a file or report folder cannot be read.

### bundle.verify_bundle

```python
verify_bundle(path: str | Path, *, public_key: Ed25519PublicKey | None = None)
```

Check a bundle against its manifest and verify the ledger inside it.

**Raises**

- InputError: If the file is not a readable zip.

## Errors

### MedAgentRxError

*class*, a subclass of `Exception`.

Base for errors caused by inputs or usage rather than by a bug.

**Args**

| Name | Description |
|---|---|
| `summary` | One line describing what went wrong. |
| `details` | Optional list of specific problems, one per line. |

### PlanError

*class*, a subclass of `MedAgentRxError`.

The change plan cannot be read or is not valid.

### InputError

*class*, a subclass of `MedAgentRxError`.

A prediction file, manifest, metadata file or path is not acceptable.

### StatsError

*class*, a subclass of `MedAgentRxError`.

A statistic cannot be computed from the data given, for example one class only.

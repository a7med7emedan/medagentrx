<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Validation results

The statistics are checked by simulation, nightly and before each release.

![Type I error, power and bootstrap coverage across prevalence and test-set size](assets/validation.svg)

**Design.** Prevalence 5, 12 and 30 percent; test sets of 500, 2,000 and 20,000 rows. Both models have binormal scores, correlated 0.8 within each row. The reference AUROC is 0.80 and the margin is 0.02.

- **Type I error.** The new model is worse by exactly the margin. The one-sided non-inferiority test at alpha 0.05 must reject between 4 and 6 percent of the time. There are 20,000 replicates per cell.
- **Power.** The two models are equally good. Power rises with the number of events.
- **Coverage.** The paired stratified bootstrap 95 percent interval of the net benefit difference at threshold 0.2, with 2,000 bootstrap replicates, must contain the true value between 93 and 97 percent of the time. There are 10,000 replicates per cell.

**Small samples.** With 25 positives (5 percent of 500 rows), the normal reference gave a type I error of 0.060. MedAgentRx therefore uses a Student t reference with `min(positives, negatives) - 1` degrees of freedom, which gives 0.054. In the same corner, the percentile interval covers about 93 percent, inside its band but near the edge. Plans with so few events also get a power warning (PERF-006).

**Cross-check.** DeLong AUC, standard errors and z statistics agree with R pROC to 1e-8 on AUC and 1e-6 on standard error and z.

The raw numbers are in [`validation.json`](assets/validation.json). Reproduce them with:

```bash
uv run python scripts/validation.py --out docs/assets
```

## Deployment QC

The multirule check of [deployment QC](qc.md) (LIVE-004) is simulated with the package's own rule code, run by run, with rejected runs left out of later windows. Each run's bias is drawn in SD units, so the results hold for any tolerance and number of control records. All five rules are on. Three settings are compared: the SD given in the plan, and the SD and mean estimated from 20 or from 60 baseline runs.

**False alarms under pure noise.** 4,000 simulated years of 365 daily runs each.

| Setting | False rejections per run | False alarms per year | Years with at least one |
|---|---|---|---|
| SD given in the plan | 0.65% | 2.4 | 86% |
| SD from 20 baseline runs | 1.88% | 6.8 | 86% |
| SD from 60 baseline runs | 0.97% | 3.5 | 85% |

With the SD known, the rate per run is close to the textbook values for these rules; 1_3s alone gives about 0.27 percent. Daily runs therefore give about two false alarms a year. An SD estimated from 20 runs is often too small, which nearly triples the rate; 60 runs halve it again. A deterministic stack that reproduces its expected scores exactly has a bias of zero on every run, so it gives no false alarms.

**Detection of a sustained shift.** 4,000 replicates per shift: 20 in-control runs, then every later run shifted by the given number of SD. Runs to detection count from the first shifted run, up to 50.

| Setting | Shift (SD) | First run | Within 10 runs | Within 50 runs | Median runs to detection |
|---|---|---|---|---|---|
| SD given in the plan | 0.5 | 1.2% | 13.7% | 59.2% | 39 |
| SD given in the plan | 1 | 3.1% | 46.4% | 97.7% | 11 |
| SD given in the plan | 2 | 17.9% | 98.8% | 100.0% | 3 |
| SD given in the plan | 3 | 51.2% | 100.0% | 100.0% | 1 |
| SD from 20 baseline runs | 0.5 | 2.7% | 23.5% | 64.7% | 30 |
| SD from 20 baseline runs | 1 | 5.4% | 51.0% | 94.2% | 10 |
| SD from 20 baseline runs | 2 | 20.9% | 97.0% | 100.0% | 3 |
| SD from 20 baseline runs | 3 | 52.8% | 100.0% | 100.0% | 1 |
| SD from 60 baseline runs | 0.5 | 1.7% | 18.3% | 63.1% | 35 |
| SD from 60 baseline runs | 1 | 4.2% | 47.3% | 96.1% | 11 |
| SD from 60 baseline runs | 2 | 19.1% | 98.0% | 100.0% | 3 |
| SD from 60 baseline runs | 3 | 54.1% | 100.0% | 100.0% | 1 |

A shift of 3 SD is caught on its first run about half the time and within ten runs always. A shift of 1 SD is caught within ten runs about half the time. Shifts larger than the per-record tolerance are also caught at once by LIVE-003, which this simulation leaves out.

The raw numbers are in [`qc-validation.json`](assets/qc-validation.json). Reproduce them with:

```bash
uv run python scripts/qc_validation.py --out docs/assets
```

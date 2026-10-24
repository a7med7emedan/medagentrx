# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Simulate the deployment QC multirule check: false alarms and detection.

Run from the repository root:
    uv run python scripts/qc_validation.py --out docs/assets

Each simulated run's bias is drawn in SD units, so the results hold for any
tolerance and number of control records. Runs are judged by the package's
own rule code, run by run, with rejected runs left out of later windows as
LIVE-004 does. Three settings are simulated: the SD given in the plan
(target bias zero), and the SD and mean estimated from 20 or from 60
baseline runs.

- False alarms: 365 daily runs of pure noise per simulated year.
- Detection: 20 in-control runs, then every later run shifted by delta SD.
  Runs to detection count from the first shifted run; a run of 50 or more
  is reported as not detected within 50.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np

from medagentrx.stats.multirule import (
    Baseline,
    estimate_baseline,
    evaluate_rules,
    given_baseline,
    standardise,
)

RULES = ("1_2s", "1_3s", "2_2s", "R_4s", "10_x")
YEARS = 4000
DAYS = 365
DETECTION_REPLICATES = 4000
SHIFTS = (0.5, 1.0, 2.0, 3.0)
LEAD_IN = 20
HORIZON = 50
SETTINGS = {"given_sd": 0, "estimated_sd_20": 20, "estimated_sd_60": 60}
"""Baseline runs per setting; 0 means the plan gives the SD."""
SEED = 20261024


def _monitor(values: np.ndarray, baseline: Baseline, history: list[float]) -> list[str]:
    """Judge each value in turn; return the rejection rules of each run ('' if none)."""
    accepted = list(history)
    outcomes = []
    for value in values:
        z = standardise([*accepted, float(value)], baseline)
        result = evaluate_rules(z, RULES)
        outcomes.append(",".join(result.rejections))
        if result.in_control:
            accepted.append(float(value))
    return outcomes


def _setting(rng: np.random.Generator, baseline_runs: int) -> tuple[Baseline, list[float]]:
    if not baseline_runs:
        return given_baseline(1.0), []
    runs = [float(v) for v in rng.normal(0.0, 1.0, baseline_runs)]
    return estimate_baseline(runs, floor=1e-12), runs


def false_alarms(rng: np.random.Generator, *, baseline_runs: int) -> dict[str, Any]:
    """Per-run and per-year false rejection under pure noise."""
    runs = rejected = years_with_alarm = 0
    by_rule: dict[str, int] = dict.fromkeys(RULES[1:], 0)
    per_year: list[int] = []
    for _ in range(YEARS):
        baseline, history = _setting(rng, baseline_runs)
        outcomes = _monitor(rng.normal(0.0, 1.0, DAYS), baseline, history)
        alarms = [o for o in outcomes if o]
        runs += DAYS
        rejected += len(alarms)
        years_with_alarm += bool(alarms)
        per_year.append(len(alarms))
        for alarm in alarms:
            for rule in alarm.split(","):
                by_rule[rule] += 1
    return {
        "per_run": rejected / runs,
        "per_year_any": years_with_alarm / YEARS,
        "mean_alarms_per_year": statistics.fmean(per_year),
        "per_run_by_rule": {rule: count / runs for rule, count in by_rule.items()},
    }


def detection(rng: np.random.Generator, shift: float, *, baseline_runs: int) -> dict[str, Any]:
    """Detection of a sustained shift of ``shift`` SD."""
    lengths: list[int] = []
    for _ in range(DETECTION_REPLICATES):
        baseline, history = _setting(rng, baseline_runs)
        lead = rng.normal(0.0, 1.0, LEAD_IN)
        accepted = list(history)
        for value in lead:
            z = standardise([*accepted, float(value)], baseline)
            if evaluate_rules(z, RULES).in_control:
                accepted.append(float(value))
        shifted = rng.normal(shift, 1.0, HORIZON)
        outcomes = _monitor(shifted, baseline, accepted)
        first = next((i + 1 for i, o in enumerate(outcomes) if o), HORIZON + 1)
        lengths.append(first)
    detected = [n for n in lengths if n <= HORIZON]
    return {
        "shift_sd": shift,
        "first_run": sum(n == 1 for n in lengths) / len(lengths),
        "within_10_runs": sum(n <= 10 for n in lengths) / len(lengths),
        "within_50_runs": len(detected) / len(lengths),
        "median_runs_to_detection": statistics.median(lengths),
        "mean_runs_to_detection_if_detected": statistics.fmean(detected) if detected else None,
    }


def main() -> None:
    """Run the simulation and write qc-validation.json."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    results: dict[str, Any] = {
        "settings": {
            "rules": list(RULES),
            "years": YEARS,
            "days_per_year": DAYS,
            "detection_replicates": DETECTION_REPLICATES,
            "lead_in_runs": LEAD_IN,
            "horizon_runs": HORIZON,
            "seed": SEED,
        }
    }
    for name, runs in SETTINGS.items():
        rng = np.random.default_rng([SEED, runs])
        results[name] = {
            "baseline_runs": runs,
            "false_alarms": false_alarms(rng, baseline_runs=runs),
            "detection": [detection(rng, s, baseline_runs=runs) for s in SHIFTS],
        }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "qc-validation.json").write_text(json.dumps(results, indent=2) + "\n")
    for name in SETTINGS:
        fa = results[name]["false_alarms"]
        print(
            f"{name}: false rejection per run {fa['per_run']:.4f}, years with an alarm "
            f"{fa['per_year_any']:.3f}, alarms per year {fa['mean_alarms_per_year']:.2f}, "
            f"by rule {fa['per_run_by_rule']}"
        )
        for d in results[name]["detection"]:
            print(
                f"  shift {d['shift_sd']} SD: first run {d['first_run']:.3f}, within 10 "
                f"{d['within_10_runs']:.3f}, within 50 {d['within_50_runs']:.3f}, median "
                f"{d['median_runs_to_detection']}"
            )


if __name__ == "__main__":
    main()

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Synthetic demo cohort and planted scenarios. No real patient data."""

from medagentrx.demo.qc_scenarios import (
    QC_SCENARIOS,
    QcScenarioResult,
    run_all_qc,
    run_qc_scenario,
)
from medagentrx.demo.scenarios import SCENARIOS, ScenarioResult, run_all, run_scenario

__all__ = [
    "QC_SCENARIOS",
    "SCENARIOS",
    "QcScenarioResult",
    "ScenarioResult",
    "run_all",
    "run_all_qc",
    "run_qc_scenario",
    "run_scenario",
]

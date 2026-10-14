# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""MedAgentRx: an executable gate for changes to clinical prediction models.

Every model update, by an engineer, a pipeline or an AI agent, is checked
against its approved change plan and receives one verdict: ACCEPTED, FAILED
or OUTSIDE_PLAN.
"""

__version__ = "0.1.1"

from medagentrx.api import CheckResult, check
from medagentrx.engine import Evaluation, Verdict, evaluate
from medagentrx.errors import InputError, MedAgentRxError, PlanError, StatsError
from medagentrx.plan import ChangePlan, load_plan

__all__ = [
    "ChangePlan",
    "CheckResult",
    "Evaluation",
    "InputError",
    "MedAgentRxError",
    "PlanError",
    "StatsError",
    "Verdict",
    "__version__",
    "check",
    "evaluate",
    "load_plan",
]

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""MedAgentRx: an executable gate for changes to clinical prediction models.

Every model update, by an engineer, a pipeline or an AI agent, is checked
against its approved change plan and receives one verdict: ACCEPTED, FAILED
or OUTSIDE_PLAN.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]

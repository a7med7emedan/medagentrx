# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Check families. Importing this package registers every check."""

from medagentrx.checks import (  # noqa: F401
    data_checks,
    doc_checks,
    life_checks,
    perf_checks,
    plan_checks,
)
from medagentrx.checks.registry import REGISTRY, Breaks, Family, Finding, Status, catalogue

__all__ = ["REGISTRY", "Breaks", "Family", "Finding", "Status", "catalogue"]

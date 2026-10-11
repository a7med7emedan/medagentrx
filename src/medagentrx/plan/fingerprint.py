# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Fingerprint of a validated plan.

The fingerprint is the SHA-256 of the plan's canonical JSON: keys sorted,
no whitespace, UTF-8. Comments and formatting in the YAML file do not change
it; any change to a value does.
"""

from __future__ import annotations

import hashlib
import json

from medagentrx.plan.models import ChangePlan


def canonical_plan_json(plan: ChangePlan) -> str:
    """Return the canonical JSON text of a plan."""
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_fingerprint(plan: ChangePlan) -> str:
    """Return the SHA-256 hex digest of the canonical plan JSON."""
    return hashlib.sha256(canonical_plan_json(plan).encode("utf-8")).hexdigest()

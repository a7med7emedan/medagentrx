# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""JSON Schema of the change plan, exported from the typed model."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from medagentrx.plan.models import ChangePlan

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "urn:medagentrx:change-plan:1.0"


@cache
def _schema() -> str:
    body = ChangePlan.model_json_schema(mode="validation", by_alias=True)
    schema: dict[str, Any] = {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **body}
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def plan_json_schema() -> dict[str, Any]:
    """Return the JSON Schema (draft 2020-12) of a change plan."""
    result: dict[str, Any] = json.loads(_schema())
    return result


def plan_json_schema_text() -> str:
    """Return the JSON Schema as stable, indented JSON text."""
    return _schema()

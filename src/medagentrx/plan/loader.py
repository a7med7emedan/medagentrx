# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Read and validate a change plan.

Order of work: read at most ``max_bytes``, parse with the hardened YAML
loader, validate against the exported JSON Schema, build the typed model,
then apply the cross-field rules. Any failure becomes one ``PlanError``
listing every problem found at that stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema.exceptions import best_match
from pydantic import ValidationError

from medagentrx.errors import PlanError
from medagentrx.io.paths import resolve_input
from medagentrx.io.text import read_text_limited
from medagentrx.plan.logic import Issue, check_logic
from medagentrx.plan.models import ChangePlan
from medagentrx.plan.schema import plan_json_schema
from medagentrx.safe_yaml import JSONValue, parse_yaml

DEFAULT_MAX_PLAN_BYTES = 1_000_000
"""Largest plan file accepted, in bytes. Real plans are a few kilobytes."""


@dataclass(frozen=True)
class LoadedPlan:
    """A valid plan with the warnings found while checking it."""

    plan: ChangePlan
    warnings: tuple[Issue, ...]


def load_plan(path: str | Path, *, max_bytes: int = DEFAULT_MAX_PLAN_BYTES) -> ChangePlan:
    """Load and validate a change plan file.

    Args:
        path: Path to ``change-plan.yaml``.
        max_bytes: Largest file size accepted.

    Returns:
        The validated plan.

    Raises:
        PlanError: If the file cannot be read or the plan is not valid.
    """
    return load_plan_with_warnings(path, max_bytes=max_bytes).plan


def load_plan_with_warnings(
    path: str | Path, *, max_bytes: int = DEFAULT_MAX_PLAN_BYTES
) -> LoadedPlan:
    """Load a plan file and also return the logic warnings."""
    real = resolve_input(path, error=PlanError)
    text = read_text_limited(real, max_bytes=max_bytes, error=PlanError)
    return parse_plan_text(text, source=str(path))


def parse_plan_text(text: str, *, source: str = "<plan>") -> LoadedPlan:
    """Validate plan text. See the module docstring for the order of work."""
    data = parse_yaml(text, source=source)
    if not isinstance(data, dict):
        raise PlanError(f"{source}: the plan must be a mapping at the top level")
    schema_errors = _schema_errors(data)
    if schema_errors:
        raise PlanError(f"{source}: the plan does not match the schema", schema_errors)
    try:
        plan = ChangePlan.model_validate(data)
    except ValidationError as exc:
        raise PlanError(f"{source}: the plan is not valid", _pydantic_errors(exc)) from None
    issues = check_logic(plan)
    errors = [str(i) for i in issues if i.level == "error"]
    if errors:
        raise PlanError(f"{source}: the plan is not consistent", errors)
    return LoadedPlan(plan=plan, warnings=tuple(i for i in issues if i.level == "warning"))


@cache
def _validator() -> Any:  # noqa: ANN401
    schema = plan_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _schema_errors(data: JSONValue) -> list[str]:
    messages: list[str] = []
    for error in sorted(_validator().iter_errors(data), key=lambda e: list(map(str, e.path))):
        chosen = _deepest(error)
        path = _format_path(chosen.absolute_path)
        messages.append(f"{path}: {chosen.message}")
    return messages


def _deepest(error: Any) -> Any:  # noqa: ANN401
    """Follow an anyOf failure into the branch that matched the input furthest.

    A union of condition or criterion kinds fails in every branch. The branch
    whose error lies deepest in the input is the one the author meant.
    """
    while error.context:
        depth = max(len(e.absolute_path) for e in error.context)
        error = best_match(e for e in error.context if len(e.absolute_path) == depth)
    return error


def _pydantic_errors(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors(include_url=False):
        parts = [p for p in error["loc"] if not (isinstance(p, str) and p.startswith("<"))]
        message = str(error["msg"]).removeprefix("Value error, ")
        messages.append(f"{_format_path(parts)}: {message}")
    return messages


def _format_path(parts: Any) -> str:  # noqa: ANN401
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or "<root>"

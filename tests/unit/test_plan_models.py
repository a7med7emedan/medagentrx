# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from medagentrx import PlanError, load_plan
from medagentrx.plan import (
    load_plan_with_warnings,
    parse_plan_text,
    plan_fingerprint,
    plan_json_schema,
    plan_json_schema_text,
)
from medagentrx.plan.models import AllCondition, AnyCondition, LeafCondition, NotCondition
from tests.conftest import EXAMPLE_DIR, EXAMPLE_PLAN, REPO_ROOT

Data = dict[str, Any]


def _load(data: Data) -> Any:
    return parse_plan_text(yaml.safe_dump(data, sort_keys=False), source="t.yaml")


def _error(data: Data) -> PlanError:
    with pytest.raises(PlanError) as exc:
        _load(data)
    return exc.value


def test_example_plan_is_valid_without_warnings() -> None:
    loaded = load_plan_with_warnings(EXAMPLE_PLAN)
    assert loaded.warnings == ()
    plan = loaded.plan
    assert plan.plan.id == "SEPSIS-RISK-PCCP"
    assert plan.plan.revision == 3
    assert [m.id for m in plan.modifications] == ["M1", "M2"]
    assert plan.performance.subgroups is not None
    assert plan.performance.subgroups.by == ["sex", "age_band", "site"]
    assert len(plan.performance.criteria) == 5


def test_example_intended_use_hash_matches_statement() -> None:
    statement = (EXAMPLE_DIR / "intended-use.txt").read_bytes()
    assert load_plan(EXAMPLE_PLAN).plan.intended_use_sha256 == hashlib.sha256(statement).hexdigest()


def test_dates_in_conditions_stay_strings() -> None:
    inclusion = load_plan(EXAMPLE_PLAN).data_management.training_inclusion
    assert isinstance(inclusion, AllCondition)
    last = inclusion.all_[2]
    assert isinstance(last, LeafCondition)
    assert last.value == ["2023-01-01", "2026-12-31"]


def test_committed_schema_matches_models() -> None:
    committed = (REPO_ROOT / "schema" / "change-plan.schema.json").read_text(encoding="utf-8")
    assert committed == plan_json_schema_text()


def _properties(node: object) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        for name, sub in node.get("properties", {}).items():
            found.append((name, sub))
        for value in node.values():
            found += _properties(value)
    elif isinstance(node, list):
        for value in node:
            found += _properties(value)
    return found


def test_every_schema_property_has_a_description() -> None:
    props = _properties(plan_json_schema())
    assert len(props) > 50
    missing = [name for name, sub in props if "description" not in sub]
    assert missing == []


def test_fingerprint_ignores_formatting_and_tracks_values(example_plan_data: Data) -> None:
    original = plan_fingerprint(load_plan(EXAMPLE_PLAN))
    reordered = dict(reversed(list(example_plan_data.items())))
    assert plan_fingerprint(_load(reordered).plan) == original
    changed = copy.deepcopy(example_plan_data)
    changed["max_updates"] = 11
    assert plan_fingerprint(_load(changed).plan) != original


def test_nested_any_and_not_conditions(example_plan_data: Data) -> None:
    example_plan_data["data_management"]["training_inclusion"] = {
        "any": [
            {"not": {"field": "site", "op": "eq", "value": "D"}},
            {"field": "consent", "op": "not_null"},
        ]
    }
    inclusion = _load(example_plan_data).plan.data_management.training_inclusion
    assert isinstance(inclusion, AnyCondition)
    assert isinstance(inclusion.any_[0], NotCondition)


@pytest.mark.parametrize(
    ("leaf", "message"),
    [
        ({"field": "x", "op": "is_null", "value": 1}, "takes no value"),
        ({"field": "x", "op": "in", "value": "A"}, "non-empty list"),
        ({"field": "x", "op": "in", "value": []}, "non-empty list"),
        ({"field": "x", "op": "between", "value": [1]}, "exactly two values"),
        ({"field": "x", "op": "between", "value": [5, 1]}, "lower value first"),
        ({"field": "x", "op": "between", "value": [1, "b"]}, "two numbers or two strings"),
        ({"field": "x", "op": "lt", "value": True}, "cannot compare a boolean"),
        ({"field": "x", "op": "eq", "value": [1, 2]}, "needs a single value"),
        ({"field": "x", "op": "ge"}, "needs a single value"),
    ],
)
def test_condition_value_rules(example_plan_data: Data, leaf: Data, message: str) -> None:
    example_plan_data["data_management"]["training_inclusion"] = {"all": [leaf]}
    error = _error(example_plan_data)
    assert any(
        d.startswith("data_management.training_inclusion.all[0]") and message in d
        for d in error.details
    ), error.details


@pytest.mark.parametrize(
    ("criterion", "message"),
    [
        (
            {
                "metric": "net_benefit",
                "test": "non_inferiority",
                "vs": ["previous"],
                "margin": 0.01,
            },
            "needs at_thresholds",
        ),
        (
            {
                "metric": "net_benefit",
                "test": "non_inferiority",
                "vs": ["previous"],
                "margin": 0.01,
                "at_thresholds": [0.1, 0.1],
            },
            "must not repeat a value",
        ),
        (
            {
                "metric": "auroc",
                "test": "non_inferiority",
                "vs": ["previous"],
                "margin": 0.01,
                "at_thresholds": [0.1],
            },
            "net_benefit only",
        ),
        (
            {
                "metric": "auroc",
                "test": "non_inferiority",
                "vs": ["anchor", "anchor"],
                "margin": 0.01,
            },
            "must not repeat a comparator",
        ),
        ({"metric": "calibration_slope", "test": "within", "bounds": [1.2, 0.8]}, "lower < upper"),
    ],
)
def test_criterion_rules(example_plan_data: Data, criterion: Data, message: str) -> None:
    example_plan_data["performance"]["criteria"].append(criterion)
    error = _error(example_plan_data)
    assert any(d.startswith("performance.criteria[5]") and message in d for d in error.details), (
        error.details
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda d: d["modifications"].append(copy.deepcopy(d["modifications"][0])),
            "modifications: duplicate modification id 'M1'",
        ),
        (
            lambda d: d["data_management"]["forbid_overlap_on"].append("patient_id"),
            "data_management.forbid_overlap_on: duplicate key 'patient_id'",
        ),
        (
            lambda d: d["performance"]["subgroups"]["by"].append("sex"),
            "performance.subgroups.by: duplicate column 'sex'",
        ),
        (
            lambda d: d["performance"]["criteria"].append(
                copy.deepcopy(d["performance"]["criteria"][2])
            ),
            "performance.criteria: duplicate criterion 'calibration_slope within'",
        ),
    ],
)
def test_logic_errors(
    example_plan_data: Data, mutate: Callable[[Data], None], expected: str
) -> None:
    mutate(example_plan_data)
    error = _error(example_plan_data)
    assert "not consistent" in error.summary
    assert expected in error.details


def test_logic_warnings(example_plan_data: Data) -> None:
    example_plan_data["data_management"]["locked_test_set"]["max_evaluations"] = 5
    example_plan_data["performance"]["criteria"] = [
        c for c in example_plan_data["performance"]["criteria"] if c["metric"] != "auroc"
    ]
    warnings = [str(w) for w in _load(example_plan_data).warnings]
    assert "data_management.locked_test_set.max_evaluations: 5 looks cannot cover 12 updates" in (
        warnings
    )
    assert "performance.criteria: no AUROC non-inferiority criterion" in warnings


def test_optional_blocks_may_be_omitted(example_plan_data: Data) -> None:
    for key in ("subgroups", "power"):
        del example_plan_data["performance"][key]
    del example_plan_data["regulatory_map"]
    plan = _load(example_plan_data).plan
    assert plan.performance.subgroups is None
    assert plan.regulatory_map is None


def test_plan_is_immutable() -> None:
    plan = load_plan(EXAMPLE_PLAN)
    with pytest.raises(Exception, match="frozen"):
        plan.max_updates = 99  # type: ignore[misc]


def test_schema_is_valid_json_with_dialect() -> None:
    schema = json.loads(plan_json_schema_text())
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["additionalProperties"] is False


def test_load_plan_accepts_path_objects(tmp_path: Path) -> None:
    target = tmp_path / "p.yaml"
    target.write_bytes(EXAMPLE_PLAN.read_bytes())
    assert load_plan(target).plan.id == "SEPSIS-RISK-PCCP"

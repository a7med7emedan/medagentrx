# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from typing import Any

import pytest
from pydantic import TypeAdapter

from medagentrx.plan.conditions import evaluate
from medagentrx.plan.models import Condition

adapter: TypeAdapter[Any] = TypeAdapter(Condition)


def cond(data: dict[str, Any]) -> Any:
    return adapter.validate_python(data)


@pytest.mark.parametrize(
    ("leaf", "row", "expected"),
    [
        ({"field": "age", "op": "ge", "value": 18}, {"age": 18}, True),
        ({"field": "age", "op": "ge", "value": 18}, {"age": 17.9}, False),
        ({"field": "age", "op": "gt", "value": 18}, {"age": 18}, False),
        ({"field": "age", "op": "lt", "value": 18}, {"age": 3}, True),
        ({"field": "age", "op": "le", "value": 18}, {"age": 18}, True),
        ({"field": "age", "op": "eq", "value": 18}, {"age": 18.0}, True),
        ({"field": "age", "op": "ne", "value": 18}, {"age": 19}, True),
        ({"field": "age", "op": "ge", "value": 18}, {"age": "adult"}, False),
        ({"field": "age", "op": "ne", "value": 18}, {"age": "adult"}, True),
        ({"field": "age", "op": "eq", "value": 18}, {"age": True}, False),
        ({"field": "age", "op": "ge", "value": 18}, {"age": None}, False),
        ({"field": "age", "op": "ge", "value": 18}, {}, False),
        ({"field": "site", "op": "in", "value": ["A", "B"]}, {"site": "A"}, True),
        ({"field": "site", "op": "in", "value": ["A", "B"]}, {"site": "C"}, False),
        ({"field": "site", "op": "not_in", "value": ["A", "B"]}, {"site": "C"}, True),
        ({"field": "site", "op": "in", "value": [1, 2]}, {"site": "1"}, False),
        ({"field": "flag", "op": "in", "value": [True]}, {"flag": 1}, False),
        (
            {"field": "d", "op": "between", "value": ["2023-01-01", "2026-12-31"]},
            {"d": "2024-05-06"},
            True,
        ),
        (
            {"field": "d", "op": "between", "value": ["2023-01-01", "2026-12-31"]},
            {"d": "2027-01-01"},
            False,
        ),
        ({"field": "d", "op": "between", "value": [1, 5]}, {"d": "3"}, False),
        ({"field": "x", "op": "is_null"}, {"x": None}, True),
        ({"field": "x", "op": "is_null"}, {"x": 0}, False),
        ({"field": "x", "op": "not_null"}, {"x": 0}, True),
        ({"field": "s", "op": "eq", "value": "yes"}, {"s": "yes"}, True),
    ],
)
def test_leaf_operators(leaf: dict[str, Any], row: dict[str, Any], expected: bool) -> None:
    assert evaluate(cond(leaf), row) is expected


def test_combinations() -> None:
    tree = cond(
        {
            "all": [
                {"field": "age", "op": "ge", "value": 18},
                {
                    "any": [
                        {"field": "site", "op": "eq", "value": "A"},
                        {"field": "vip", "op": "not_null"},
                    ]
                },
                {"not": {"field": "excluded", "op": "eq", "value": True}},
            ]
        }
    )
    assert evaluate(tree, {"age": 40, "site": "A", "excluded": False})
    assert evaluate(tree, {"age": 40, "site": "B", "vip": "x", "excluded": None})
    assert not evaluate(tree, {"age": 40, "site": "B"})
    assert not evaluate(tree, {"age": 40, "site": "A", "excluded": True})

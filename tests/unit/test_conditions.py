# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from medagentrx.plan.conditions import evaluate, evaluate_columns
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


# Vectorised evaluation agrees with the row-by-row evaluator --------------------------


FIELDS = ("a", "b", "c", "absent")
literals = st.one_of(
    st.integers(-3, 3),
    st.sampled_from([0.5, -1.5, 2.0, 2**53 + 1]),
    st.sampled_from(["", "A", "B", "2024-01-01", "2025-06-30"]),
    st.booleans(),
)
cells = st.one_of(st.none(), literals, st.sampled_from([float("nan"), float("inf")]))
leaves = st.one_of(
    st.builds(
        lambda f, op, v: {"field": f, "op": op, "value": v},
        st.sampled_from(FIELDS),
        st.sampled_from(["eq", "ne", "lt", "le", "gt", "ge"]),
        literals,
    ),
    st.builds(
        lambda f, op, v: {"field": f, "op": op, "value": v},
        st.sampled_from(FIELDS),
        st.sampled_from(["in", "not_in"]),
        st.lists(literals, min_size=1, max_size=3),
    ),
    st.builds(
        lambda f, pair: {"field": f, "op": "between", "value": sorted(pair)},
        st.sampled_from(FIELDS),
        st.one_of(
            st.lists(st.integers(-3, 3), min_size=2, max_size=2),
            st.lists(st.sampled_from(["A", "B", "2024-01-01"]), min_size=2, max_size=2),
        ),
    ),
    st.builds(
        lambda f, op: {"field": f, "op": op},
        st.sampled_from(FIELDS),
        st.sampled_from(["is_null", "not_null"]),
    ),
)
trees = st.recursive(
    leaves,
    lambda inner: st.one_of(
        st.builds(lambda xs: {"all": xs}, st.lists(inner, max_size=3)),
        st.builds(lambda xs: {"any": xs}, st.lists(inner, max_size=3)),
        st.builds(lambda x: {"not": x}, inner),
    ),
    max_leaves=6,
)
column_kinds = st.sampled_from(["int", "float", "str", "bool", "mixed"])


def _column_values(kind: str, n: int) -> st.SearchStrategy[list[object]]:
    pools: dict[str, st.SearchStrategy[object]] = {
        "int": st.integers(-4, 4),
        "float": st.sampled_from([-1.5, 0.5, 2.0, float("nan"), float("inf")]),
        "str": st.sampled_from(["", "A", "B", "2024-01-01", "2025-06-30"]),
        "bool": st.booleans(),
        "mixed": cells,
    }
    return st.lists(st.one_of(st.none(), pools[kind]), min_size=n, max_size=n)


@st.composite
def tables(draw: st.DrawFn) -> tuple[dict[str, list[object]], int]:
    n = draw(st.integers(0, 12))
    columns = {name: draw(_column_values(draw(column_kinds), n)) for name in FIELDS[:3]}
    return columns, n


@settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
@given(tree=trees, table=tables())
def test_vectorised_matches_row_by_row(tree: dict[str, Any], table: Any) -> None:
    try:
        condition = cond(tree)
    except ValidationError:
        return
    columns, n = table
    mask = evaluate_columns(condition, columns, n)
    rows = [{name: values[i] for name, values in columns.items()} for i in range(n)]
    assert mask.tolist() == [evaluate(condition, row) for row in rows]


def test_vectorised_handles_large_integers_exactly() -> None:
    condition = cond({"field": "id", "op": "eq", "value": 2**53 + 1})
    mask = evaluate_columns(condition, {"id": [2**53, 2**53 + 1, None]}, 3)
    assert mask.tolist() == [False, True, False]
    with_nan = evaluate_columns(condition, {"id": [float("nan"), 2**53 + 1]}, 2)
    assert with_nan.tolist() == [False, True]
    huge = cond({"field": "id", "op": "gt", "value": 0})
    assert evaluate_columns(huge, {"id": [10**400, 1]}, 2).tolist() == [True, True]

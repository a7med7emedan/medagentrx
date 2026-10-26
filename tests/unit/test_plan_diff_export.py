# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import csv
import io
import json
from typing import Any

from medagentrx.export import COLUMNS, export_ledger, ledger_rows
from medagentrx.plan import load_plan
from medagentrx.plan.diff import _walk, diff_plans
from medagentrx.plan.models import ChangePlan
from tests.conftest import EXAMPLE_PLAN


def _plan(edit: Any = None) -> ChangePlan:
    data = load_plan(EXAMPLE_PLAN).model_dump(mode="json", by_alias=True, exclude_none=True)
    if edit:
        edit(data)
    return ChangePlan.model_validate(data)


def test_identical_plans() -> None:
    result = diff_plans(_plan(), load_plan(EXAMPLE_PLAN))
    assert result.identical
    assert not result.revision_unchanged
    assert result.old_fingerprint == result.new_fingerprint
    assert result.to_dict()["changes"] == []


def test_changed_values_and_revision() -> None:
    def edit(data: dict[str, Any]) -> None:
        data["plan"]["revision"] = 4
        data["performance"]["criteria"][0]["margin"] = 0.03

    result = diff_plans(_plan(), _plan(edit))
    paths = {c.path: (c.kind, c.old, c.new) for c in result.changes}
    assert paths == {
        "performance.criteria[0].margin": ("changed", 0.02, 0.03),
        "plan.revision": ("changed", 3, 4),
    }
    assert not result.revision_unchanged


def test_modifications_are_matched_by_id() -> None:
    def edit(data: dict[str, Any]) -> None:
        data["modifications"] = [
            {**data["modifications"][1], "automatic": True},
            {"id": "M3", "type": "fine_tune", "automatic": False, "scope": "local"},
        ]

    result = diff_plans(_plan(), _plan(edit))
    kinds = {c.path: c.kind for c in result.changes}
    assert kinds == {
        "modifications[M1]": "removed",
        "modifications[M2].automatic": "changed",
        "modifications[M3]": "added",
    }
    assert result.revision_unchanged
    assert result.to_dict()["revision_unchanged"] is True


def test_keys_and_positional_lists() -> None:
    changes: list[Any] = []
    _walk({"a": 1, "b": [1, 2]}, {"b": [1], "c": 3}, "", changes)
    _walk({"x": [{"id": "a"}, {"id": "a"}]}, {"x": [{"id": "a"}]}, "", changes)
    _walk({"y": [1]}, {"y": [1, 2]}, "", changes)
    assert [(c.path, c.kind) for c in changes] == [
        ("a", "removed"),
        ("b[1]", "removed"),
        ("c", "added"),
        ("x[1]", "removed"),
        ("y[1]", "added"),
    ]


ENTRIES: list[dict[str, Any]] = [
    {
        "seq": 0,
        "recorded_at": "2026-06-01T06:00:00+00:00",
        "kind": "evaluation",
        "plan": {"id": "P", "revision": 1},
        "candidate_version": '=HYPERLINK("x")',
        "previous_version": "2.0.0",
        "modification_id": "M1",
        "verdict": "FAILED",
        "failed_checks": ["PERF-001", "PERF-005"],
        "warnings": [],
        "touched_test_set": True,
        "alpha": {"used": 0.004},
        "hash": "h0",
        "prev_hash": "g",
    },
    {
        "seq": 1,
        "kind": "release",
        "plan": {"id": "P", "revision": 1},
        "candidate_version": "2.1.0",
        "evaluation": {"seq": 0},
        "hash": "h1",
        "prev_hash": "h0",
    },
    {
        "seq": 2,
        "kind": "qc",
        "model_version": "2.1.0",
        "verdict": "IN_CONTROL",
        "warnings": ["LIVE-004"],
        "touched_test_set": False,
        "qc": {"bias": -1e-7},
        "hash": "h2",
        "prev_hash": "h1",
    },
]


def test_rows() -> None:
    rows = ledger_rows(ENTRIES)
    assert [r["version"] for r in rows] == ['=HYPERLINK("x")', "2.1.0", "2.1.0"]
    assert rows[1]["follows_entry"] == 0
    assert rows[2]["qc_bias"] == -1e-7
    assert rows[0]["alpha_used"] == 0.004
    assert all(set(r) == set(COLUMNS) for r in rows)


def test_csv_quotes_formulas() -> None:
    table = list(csv.reader(io.StringIO(export_ledger(ENTRIES, "csv"))))
    assert table[0] == list(COLUMNS)
    first = dict(zip(COLUMNS, table[1], strict=True))
    assert first["version"] == '\'=HYPERLINK("x")'
    assert first["failed_checks"] == "PERF-001;PERF-005"
    assert first["touched_test_set"] == "true"
    third = dict(zip(COLUMNS, table[3], strict=True))
    assert third["qc_bias"] == "'-1e-07"
    assert third["touched_test_set"] == "false"
    assert third["plan_id"] == ""


def test_json_export() -> None:
    data = json.loads(export_ledger(ENTRIES, "json"))
    assert data[0]["failed_checks"] == ["PERF-001", "PERF-005"]
    assert data[2]["qc_bias"] == -1e-7

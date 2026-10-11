# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from medagentrx import InputError, load_plan
from medagentrx.io.manifest import load_manifest
from medagentrx.io.metadata import load_model_meta
from medagentrx.plan.conditions import condition_fields
from medagentrx.plan.models import AnyCondition, LeafCondition, NotCondition
from tests.conftest import EXAMPLE_PLAN, write_table

MANIFEST = {
    "row_id": ["t1", "t2", "t3"],
    "patient_id": ["p1", "p1", "p2"],
    "age": ["34", "", "71"],
    "site": ["A", "B", "C"],
    "admission_date": ["2024-02-01", "2025-07-13", "2023-01-05"],
    "lactate": ["1.5", "2", "0.9"],
}


def test_condition_fields_of_example_plan() -> None:
    inclusion = load_plan(EXAMPLE_PLAN).data_management.training_inclusion
    assert condition_fields(inclusion) == ["age", "site", "admission_date"]


def test_condition_fields_nested() -> None:
    condition = AnyCondition.model_validate(
        {
            "any": [
                {"not": {"field": "b", "op": "is_null"}},
                {
                    "all": [
                        {"field": "a", "op": "eq", "value": 1},
                        {"field": "b", "op": "ne", "value": 2},
                    ]
                },
            ]
        }
    )
    assert condition_fields(condition) == ["b", "a"]
    assert condition_fields(LeafCondition(field="x", op="not_null")) == ["x"]
    assert condition_fields(
        NotCondition.model_validate({"not": {"field": "y", "op": "is_null"}})
    ) == ["y"]


def test_csv_manifest_types_columns(tmp_path: Path) -> None:
    manifest = load_manifest(
        write_table(tmp_path / "m.csv", MANIFEST), required_fields=["age", "site", "admission_date"]
    )
    assert manifest.n == 3
    assert manifest.patient_id == ("p1", "p1", "p2")
    assert manifest.columns["age"] == (34, None, 71)
    assert manifest.columns["lactate"] == (1.5, 2.0, 0.9)
    assert manifest.columns["site"] == ("A", "B", "C")
    assert manifest.columns["admission_date"] == ("2024-02-01", "2025-07-13", "2023-01-05")


def test_parquet_manifest_keeps_native_types_and_dates(tmp_path: Path) -> None:
    import datetime as dt

    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "m.parquet"
    pq.write_table(
        pa.table(
            {
                "row_id": ["t1", "t2"],
                "patient_id": pa.array([10, 11]),
                "age": pa.array([40, None], type=pa.int16()),
                "admission_date": pa.array([dt.date(2024, 1, 2), dt.date(2025, 3, 4)]),
            }
        ),
        path,
    )
    manifest = load_manifest(path, required_fields=["age"])
    assert manifest.patient_id == ("10", "11")
    assert manifest.columns["age"] == (40, None)
    assert manifest.columns["admission_date"] == ("2024-01-02", "2025-03-04")


@pytest.mark.parametrize(
    ("change", "required", "message"),
    [
        ({}, ["weight"], "missing required column(s): weight"),
        ({"row_id": ["t1", "t1", "t3"]}, [], "row 2: duplicate row_id 't1'"),
        ({"patient_id": ["p1", "", "p2"]}, [], "row 2: patient_id is missing"),
        ({"lactate": ["1.5", "nan", "0.9"]}, [], "row 2: lactate is nan, not a number"),
    ],
)
def test_manifest_errors(
    tmp_path: Path, change: dict[str, list[str]], required: list[str], message: str
) -> None:
    path = write_table(tmp_path / "m.csv", {**MANIFEST, **change})
    with pytest.raises(InputError) as exc:
        load_manifest(path, required_fields=required)
    assert message in str(exc.value)


def test_empty_manifest(tmp_path: Path) -> None:
    path = tmp_path / "m.csv"
    path.write_text("row_id,patient_id\n", encoding="utf-8")
    with pytest.raises(InputError, match="no data rows"):
        load_manifest(path)


META = """\
version: "2.1.0"
previous_version: "2.0.0"
modification_id: M1
architecture_sha256: "{h}"
intended_use_sha256: "{h}"
trained_at: 2026-04-01T10:00:00Z
training_manifest_sha256: "{h}"
""".format(h="a" * 64)


def test_model_meta_loads(tmp_path: Path) -> None:
    path = tmp_path / "model.yaml"
    path.write_text(META, encoding="utf-8")
    meta = load_model_meta(path)
    assert meta.version == "2.1.0"
    assert meta.modification_id == "M1"
    assert meta.trained_at.isoformat().startswith("2026-04-01")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (META + "extra: 1\n", "extra: Extra inputs are not permitted"),
        (META.replace("modification_id: M1\n", ""), "modification_id: Field required"),
        (
            META.replace('"' + "a" * 64 + '"', '"xyz"', 1),
            "architecture_sha256: String should match",
        ),
        ("- a\n", "model metadata must be a mapping"),
        ("a: &x 1\nb: *x\n", "anchors and aliases are not allowed"),
        ("a: !!python/name:os.system\n", "not valid YAML"),
    ],
)
def test_model_meta_errors(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "model.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(InputError) as exc:
        load_model_meta(path)
    assert message in str(exc.value)

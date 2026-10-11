# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import numpy as np
import pytest

from medagentrx import InputError
from medagentrx.io.predictions import RowMismatchError, align, compare_rows, load_predictions
from tests.conftest import write_table

Columns = dict[str, list[object]]


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_load_predictions(tmp_path: Path, predictions_columns: Columns, suffix: str) -> None:
    path = write_table(tmp_path / f"p{suffix}", predictions_columns)
    preds = load_predictions(path, subgroup_columns=["site"])
    assert preds.n == 4
    assert preds.row_id.tolist() == ["r2", "r1", "r3", "r4"]
    assert preds.y_true.dtype == np.int8
    assert preds.y_true.tolist() == [1, 0, 0, 1]
    assert preds.y_score.dtype == np.float64
    assert preds.y_score.tolist() == [0.9, 0.1, 0.35, 0.6]
    assert preds.subgroups["site"].tolist() == ["A", "B", "A", "C"]
    assert preds.source == str(path)


def test_csv_and_parquet_agree(tmp_path: Path, predictions_columns: Columns) -> None:
    a = load_predictions(
        write_table(tmp_path / "p.csv", predictions_columns), subgroup_columns=["site"]
    )
    b = load_predictions(
        write_table(tmp_path / "p.parquet", predictions_columns), subgroup_columns=["site"]
    )
    for field in ("row_id", "y_true", "y_score"):
        assert np.array_equal(getattr(a, field), getattr(b, field))
    assert np.array_equal(a.subgroups["site"], b.subgroups["site"])


def test_arrays_are_read_only(tmp_path: Path, predictions_columns: Columns) -> None:
    preds = load_predictions(write_table(tmp_path / "p.csv", predictions_columns))
    with pytest.raises(ValueError, match="read-only"):
        preds.y_score[0] = 0.5


def test_parquet_variants(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "row_id": pa.array(["a", "b"]).dictionary_encode(),
            "y_true": pa.array([True, False]),
            "y_score": pa.array([1, 0], type=pa.int64()),
            "site": pa.array([1, 2], type=pa.int32()),
        }
    )
    path = tmp_path / "v.pq"
    pq.write_table(table, path)
    preds = load_predictions(path, subgroup_columns=["site"])
    assert preds.y_true.tolist() == [1, 0]
    assert preds.y_score.tolist() == [1.0, 0.0]
    assert preds.subgroups["site"].tolist() == ["1", "2"]


def test_csv_with_byte_order_mark_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_bytes("﻿row_id,y_true,y_score\nx, 1 ,0.5\n\ny,0,0.25\n".encode())
    preds = load_predictions(path)
    assert preds.row_id.tolist() == ["x", "y"]
    assert preds.y_true.tolist() == [1, 0]


def test_align_reorders_to_reference(tmp_path: Path, predictions_columns: Columns) -> None:
    ref = load_predictions(
        write_table(tmp_path / "ref.csv", predictions_columns), subgroup_columns=["site"]
    )
    shuffled = {k: list(reversed(v)) for k, v in predictions_columns.items()}
    other = load_predictions(
        write_table(tmp_path / "other.csv", shuffled), subgroup_columns=["site"]
    )
    aligned = align(ref, other)
    assert aligned.row_id.tolist() == ref.row_id.tolist()
    assert aligned.y_score.tolist() == ref.y_score.tolist()
    assert aligned.subgroups["site"].tolist() == ref.subgroups["site"].tolist()
    assert not aligned.y_score.flags.writeable


def test_align_reports_every_kind_of_mismatch(tmp_path: Path) -> None:
    ref = load_predictions(
        write_table(
            tmp_path / "ref.csv",
            {"row_id": [f"r{i}" for i in range(10)], "y_true": [0] * 10, "y_score": [0.5] * 10},
        )
    )
    other = load_predictions(
        write_table(
            tmp_path / "other.csv",
            {
                "row_id": ["r0", "r1", "r2", "x1"],
                "y_true": [1, 0, 0, 0],
                "y_score": [0.5] * 4,
            },
        )
    )
    mismatch = compare_rows(ref, other)
    assert mismatch.missing == ("r3", "r4", "r5", "r6", "r7", "r8", "r9")
    assert mismatch.extra == ("x1",)
    assert mismatch.label_changed == ("r0",)
    with pytest.raises(RowMismatchError) as exc:
        align(ref, other)
    assert exc.value.mismatch == mismatch
    assert exc.value.details == (
        "7 missing rows: 'r3', 'r4', 'r5', 'r6', 'r7' and 2 more",
        "1 extra rows: 'x1'",
        "1 changed labels: 'r0'",
    )
    assert not compare_rows(ref, ref)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"y_true": [1, 0, 2, 1]}, "row 3 (row_id 'r3'): y_true must be 0 or 1, got '2'"),
        ({"y_true": [1, 0, "yes", 1]}, "y_true must be 0 or 1, got 'yes'"),
        ({"y_score": [0.9, "nan", 0.3, 0.6]}, "row 2 (row_id 'r1'): y_score must be a finite"),
        ({"y_score": [0.9, "inf", 0.3, 0.6]}, "y_score must be a finite number"),
        ({"y_score": [0.9, "high", 0.3, 0.6]}, "y_score must be a finite number, got 'high'"),
        ({"y_score": [0.9, 1.5, 0.3, 0.6]}, "y_score 1.5 is outside [0, 1]"),
        ({"y_score": [0.9, -0.1, 0.3, 0.6]}, "y_score -0.1 is outside [0, 1]"),
        ({"row_id": ["r2", "r1", "r2", "r4"]}, "row 3: duplicate row_id 'r2'"),
        ({"row_id": ["r2", "", "r3", "r4"]}, "row 2: row_id must be a non-empty string"),
        ({"row_id": ["r2", "r\t1", "r3", "r4"]}, "must not contain tabs or line breaks"),
        ({"site": ["A", "", "A", "C"]}, "row 2 (row_id 'r1'): site is missing"),
    ],
)
def test_invalid_values_name_column_and_row(
    tmp_path: Path, predictions_columns: Columns, change: Columns, message: str
) -> None:
    path = write_table(tmp_path / "bad.csv", {**predictions_columns, **change})
    with pytest.raises(InputError) as exc:
        load_predictions(path, subgroup_columns=["site"])
    assert message in str(exc.value)


def test_parquet_nulls_and_nan_are_refused(tmp_path: Path) -> None:
    columns: Columns = {"row_id": ["a", "b"], "y_true": [1, None], "y_score": [0.5, 0.5]}
    with pytest.raises(InputError, match="y_true must be 0 or 1, got None"):
        load_predictions(write_table(tmp_path / "n.parquet", columns))
    columns = {"row_id": ["a", "b"], "y_true": [1, 0], "y_score": [0.5, float("nan")]}
    with pytest.raises(InputError, match="y_score must be a finite number"):
        load_predictions(write_table(tmp_path / "nan.parquet", columns))
    columns = {"row_id": ["a", "b"], "y_true": [1, 0], "y_score": [0.5, None]}
    with pytest.raises(InputError, match="y_score must be a finite number, got None"):
        load_predictions(write_table(tmp_path / "none.parquet", columns))
    columns = {"row_id": ["a", None], "y_true": [1, 0], "y_score": [0.5, 0.4]}
    with pytest.raises(InputError, match="row_id must be a non-empty string"):
        load_predictions(write_table(tmp_path / "id.parquet", columns))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "the file is empty"),
        ("row_id,y_true,y_score\n", "no data rows"),
        ("row_id,y_true\na,1\n", "missing required column(s): y_score"),
        ("row_id,y_true,y_score,y_true\na,1,0.5,1\n", "column 'y_true' appears more than once"),
        ("row_id,y_true,y_score\na,1\n", "line 2 has 2 fields, expected 3"),
        ('row_id,y_true,y_score\n"a,1,0.5\n', "not valid CSV"),
    ],
)
def test_malformed_csv(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "m.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(InputError) as exc:
        load_predictions(path)
    assert message in str(exc.value)


def test_unsupported_suffix_and_bad_files(tmp_path: Path) -> None:
    other = tmp_path / "p.xlsx"
    other.write_bytes(b"PK")
    with pytest.raises(InputError, match=r"unsupported file type '\.xlsx'"):
        load_predictions(other)
    fake = tmp_path / "p.parquet"
    fake.write_bytes(b"not parquet at all")
    with pytest.raises(InputError, match="not a readable Parquet file"):
        load_predictions(fake)
    latin = tmp_path / "l.csv"
    latin.write_bytes("row_id,y_true,y_score\ncaf\xe9,1,0.5\n".encode("latin-1"))
    with pytest.raises(InputError, match="not UTF-8 text"):
        load_predictions(latin)


def test_peek_columns(tmp_path: Path, predictions_columns: Columns) -> None:
    from medagentrx.io.tables import peek_columns

    expected = ["row_id", "y_true", "y_score", "site"]
    assert peek_columns(write_table(tmp_path / "p.csv", predictions_columns)) == expected
    assert peek_columns(write_table(tmp_path / "p.parquet", predictions_columns)) == expected
    latin = tmp_path / "l.csv"
    latin.write_bytes("caf\xe9,b\n".encode("latin-1"))
    with pytest.raises(InputError, match="not UTF-8"):
        peek_columns(latin)
    broken = tmp_path / "b.parquet"
    broken.write_bytes(b"nope")
    with pytest.raises(InputError, match="cannot read the header"):
        peek_columns(broken)
    other = tmp_path / "x.json"
    other.write_text("{}", encoding="utf-8")
    with pytest.raises(InputError, match="unsupported file type"):
        peek_columns(other)

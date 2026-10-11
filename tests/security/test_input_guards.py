# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Inputs are data only, bounded in size, and read only from where they should be."""

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from medagentrx import InputError, PlanError, load_plan
from medagentrx.io.limits import Limits
from medagentrx.io.paths import resolve_input, safe_output_path
from medagentrx.io.predictions import load_predictions
from tests.conftest import EXAMPLE_PLAN, requires_symlinks, write_table

Columns = dict[str, list[object]]


@requires_symlinks
def test_symlink_inside_base_is_followed(tmp_path: Path, predictions_columns: Columns) -> None:
    target = write_table(tmp_path / "real.csv", predictions_columns)
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    assert load_predictions(link, base=tmp_path).n == 4


@requires_symlinks
def test_symlink_escaping_base_is_refused(tmp_path: Path, predictions_columns: Columns) -> None:
    outside = tmp_path / "outside"
    inside = tmp_path / "work"
    outside.mkdir()
    inside.mkdir()
    target = write_table(outside / "secret.csv", predictions_columns)
    (inside / "link.csv").symlink_to(target)
    with pytest.raises(InputError, match="points outside"):
        load_predictions(inside / "link.csv", base=inside)


@requires_symlinks
def test_symlinked_directory_escaping_base_is_refused(
    tmp_path: Path, predictions_columns: Columns
) -> None:
    outside = tmp_path / "outside"
    inside = tmp_path / "work"
    outside.mkdir()
    inside.mkdir()
    write_table(outside / "p.csv", predictions_columns)
    (inside / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(InputError, match="points outside"):
        load_predictions(inside / "data" / "p.csv", base=inside)


@requires_symlinks
def test_plan_symlink_escaping_working_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "plan.yaml").symlink_to(EXAMPLE_PLAN)
    monkeypatch.chdir(work)
    with pytest.raises(PlanError, match="points outside"):
        load_plan("plan.yaml")


def test_missing_and_special_files(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="file not found"):
        resolve_input(tmp_path / "nope.csv")
    with pytest.raises(InputError, match="not a regular file"):
        resolve_input(tmp_path)
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe.csv"
        os.mkfifo(fifo)
        with pytest.raises(InputError, match="not a regular file"):
            load_predictions(fifo)


def test_oversized_file_is_refused_before_reading(
    tmp_path: Path, predictions_columns: Columns
) -> None:
    path = write_table(tmp_path / "p.csv", predictions_columns)
    with pytest.raises(InputError, match="larger than the limit of 20 bytes"):
        load_predictions(path, limits=Limits(max_file_bytes=20))


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_too_many_rows_is_refused(
    tmp_path: Path, predictions_columns: Columns, suffix: str
) -> None:
    path = write_table(tmp_path / f"p{suffix}", predictions_columns)
    with pytest.raises(InputError, match="limit of 3"):
        load_predictions(path, limits=Limits(max_rows=3))


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Limits(max_rows=0)


def test_nested_parquet_column_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "nested.parquet"
    pq.write_table(
        pa.table(
            {
                "row_id": ["a", "b"],
                "y_true": [1, 0],
                "y_score": pa.array([[0.1], [0.2]]),
            }
        ),
        path,
    )
    with pytest.raises(InputError, match="column 'y_score' has nested type"):
        load_predictions(path)


@pytest.mark.parametrize(
    "name", ["../escape.html", "/etc/passwd", "a/../../b", "", "..", "sub/../../x"]
)
def test_output_names_cannot_escape(tmp_path: Path, name: str) -> None:
    with pytest.raises(InputError):
        safe_output_path(tmp_path, name)


@requires_symlinks
def test_output_through_symlink_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.html").symlink_to(tmp_path / "elsewhere.html")
    with pytest.raises(InputError, match="symbolic link"):
        safe_output_path(out, "report.html")
    (out / "sub").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(InputError, match="outside the output directory"):
        safe_output_path(out, "sub/x.html")


def test_plain_output_names_are_allowed(tmp_path: Path) -> None:
    assert safe_output_path(tmp_path, "report.html") == tmp_path.resolve() / "report.html"
    assert safe_output_path(tmp_path, "figs/a.svg") == tmp_path.resolve() / "figs" / "a.svg"


@requires_symlinks
def test_init_refuses_symlink_target(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from medagentrx.cli import app

    link = tmp_path / "change-plan.yaml"
    link.symlink_to(tmp_path / "elsewhere.yaml")
    result = CliRunner().invoke(app, ["init", "--defaults", "--out", str(link), "--force"])
    assert result.exit_code == 3
    assert "symbolic link" in result.output
    assert not (tmp_path / "elsewhere.yaml").exists()

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from typer.testing import CliRunner

from medagentrx.cli import app
from medagentrx.exit_codes import ExitCode
from medagentrx.io.fingerprint import fingerprint_file
from tests.conftest import write_table

KNOWN_ANSWER = "2c73943c03c4ac1ea182d666a6e0ad41efed0bc3815349861d37220432c4f305"
EXAMPLE: dict[str, list[object]] = {
    "row_id": ["r2", "r1", "r3"],
    "y_true": [1, 0, 0],
    "y_score": [0.8, 0.2, 0.4],
}


def test_known_answer_vector(tmp_path: Path) -> None:
    assert fingerprint_file(write_table(tmp_path / "t.csv", EXAMPLE)) == KNOWN_ANSWER


def test_known_answer_matches_docs() -> None:
    docs = (Path(__file__).resolve().parents[2] / "docs" / "fingerprint.md").read_text()
    assert KNOWN_ANSWER in docs


def test_scores_and_extra_columns_do_not_matter(tmp_path: Path) -> None:
    other: dict[str, list[object]] = {
        **EXAMPLE,
        "y_score": [0.1, 0.9, 0.5],
        "site": ["A", "B", "C"],
    }
    assert fingerprint_file(write_table(tmp_path / "t.parquet", other)) == KNOWN_ANSWER


def test_cli_prints_fingerprint(tmp_path: Path) -> None:
    path = write_table(tmp_path / "t.csv", EXAMPLE)
    result = CliRunner().invoke(app, ["fingerprint", str(path)])
    assert result.exit_code == 0
    assert result.output == KNOWN_ANSWER + "\n"


def test_cli_enforces_limits(tmp_path: Path) -> None:
    path = write_table(tmp_path / "t.csv", EXAMPLE)
    rows = CliRunner().invoke(app, ["fingerprint", str(path), "--max-rows", "2"])
    assert rows.exit_code == ExitCode.USAGE_ERROR
    assert "more than the limit of 2 rows" in rows.output
    size = CliRunner().invoke(app, ["fingerprint", str(path), "--max-file-bytes", "10"])
    assert size.exit_code == ExitCode.USAGE_ERROR
    assert "larger than the limit of 10 bytes" in size.output

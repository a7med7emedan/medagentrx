# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "sepsis-risk"
EXAMPLE_PLAN = EXAMPLE_DIR / "change-plan.yaml"


def _symlinks_supported() -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        link = Path(tmp) / "link"
        try:
            link.symlink_to(Path(tmp) / "target")
        except (OSError, NotImplementedError):
            return False
    return True


requires_symlinks = pytest.mark.skipif(
    not _symlinks_supported(), reason="symbolic links are not available"
)


@pytest.fixture
def example_plan_data() -> dict[str, object]:
    """The example plan as plain data, ready to be broken by a test."""
    data: dict[str, object] = yaml.safe_load(EXAMPLE_PLAN.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def write_plan(tmp_path: Path) -> Callable[[object], Path]:
    """Write plan data or raw text to a file and return its path."""

    def _write(content: object) -> Path:
        path = tmp_path / "change-plan.yaml"
        text = content if isinstance(content, str) else yaml.safe_dump(content, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        return path

    return _write


def write_table(path: Path, columns: Mapping[str, Sequence[object]]) -> Path:
    """Write columns as CSV or Parquet, chosen by the file suffix."""
    if path.suffix == ".csv":
        import csv

        names = list(columns)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(names)
            writer.writerows(zip(*(columns[n] for n in names), strict=True))
    else:
        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(pa.table(columns), path)
    return path


@pytest.fixture
def predictions_columns() -> dict[str, list[object]]:
    """A small valid prediction table with one subgroup column."""
    return {
        "row_id": ["r2", "r1", "r3", "r4"],
        "y_true": [1, 0, 0, 1],
        "y_score": [0.9, 0.1, 0.35, 0.6],
        "site": ["A", "B", "A", "C"],
    }

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "sepsis-risk"
EXAMPLE_PLAN = EXAMPLE_DIR / "change-plan.yaml"


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

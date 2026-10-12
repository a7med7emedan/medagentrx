# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT


def test_agent_loop_stops_when_the_guard_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location(
        "agent_loop", REPO_ROOT / "examples" / "agent_loop.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    log = module.run(tmp_path, replicates=100)
    assert len(log) == 21
    assert log[-1].endswith("Refused: outside the plan (DATA-004) (0 looks left)")
    printed = capsys.readouterr().out
    assert "The agent may make: M1" in printed
    assert "Stopping the search." in printed

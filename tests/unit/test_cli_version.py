# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import runpy
import sys

import pytest
from typer.testing import CliRunner

from medagentrx import __version__
from medagentrx.cli import app


def test_version_command_prints_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"medagentrx {__version__}"


def test_no_arguments_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def test_module_entry_point_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["medagentrx", "version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("medagentrx", run_name="__main__")
    assert exc.value.code == 0

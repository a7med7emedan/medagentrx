# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path

import pytest
import typer

from medagentrx.cli import app, run
from medagentrx.exit_codes import ExitCode
from medagentrx.io.fingerprint import fingerprint_file
from medagentrx.settings import (
    ENV_VAR,
    MAX_SETTINGS_BYTES,
    Settings,
    SettingsError,
    default_map,
    find_settings,
)
from tests.conftest import write_table

GROUP = typer.main.get_command(app)


def _settings(tmp_path: Path, text: str, name: str = "medagentrx.toml") -> Settings:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return find_settings(tmp_path, environ={})


def test_no_settings(tmp_path: Path) -> None:
    found = find_settings(tmp_path, environ={})
    assert found.source is None
    assert default_map(GROUP, found) == {}


def test_own_file_wins_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.medagentrx]\nledger = "a"\n', "utf-8")
    found = _settings(tmp_path, 'ledger = "b"\n')
    assert found.source == tmp_path / "medagentrx.toml"
    assert found.values == {"ledger": "b"}


def test_pyproject_table(tmp_path: Path) -> None:
    found = _settings(tmp_path, "[tool.medagentrx.check]\nseed = 3\n", name="pyproject.toml")
    assert found.source == tmp_path / "pyproject.toml"
    assert default_map(GROUP, found) == {"check": {"seed": 3}}


def test_pyproject_without_a_table_is_ignored(tmp_path: Path) -> None:
    found = _settings(tmp_path, '[project]\nname = "x"\n', name="pyproject.toml")
    assert found.source is None


def test_pyproject_table_must_be_a_table(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="must be a table"):
        _settings(tmp_path, "[tool]\nmedagentrx = 3\n", name="pyproject.toml")


def test_environment_variable(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.toml"
    other.write_text('ledger = "x.jsonl"\n', "utf-8")
    (tmp_path / "medagentrx.toml").write_text('ledger = "y.jsonl"\n', "utf-8")
    found = find_settings(tmp_path, environ={ENV_VAR: "elsewhere.toml"})
    assert found.source == other
    assert find_settings(tmp_path, environ={ENV_VAR: ""}).source is None
    with pytest.raises(SettingsError, match="not a file"):
        find_settings(tmp_path, environ={ENV_VAR: "missing.toml"})
    project = tmp_path / "sub" / "pyproject.toml"
    project.parent.mkdir()
    project.write_text('[tool.medagentrx]\nledger = "z"\n', "utf-8")
    assert find_settings(tmp_path, environ={ENV_VAR: str(project)}).values == {"ledger": "z"}


def test_bad_files(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="not valid TOML"):
        _settings(tmp_path, "ledger = \n")
    (tmp_path / "medagentrx.toml").write_bytes(b"x" * (MAX_SETTINGS_BYTES + 1))
    with pytest.raises(SettingsError, match="larger than"):
        find_settings(tmp_path, environ={})
    (tmp_path / "medagentrx.toml").write_bytes(b'ledger = "\xff"\n')
    with pytest.raises(SettingsError, match="cannot be read"):
        find_settings(tmp_path, environ={})


def test_shared_and_command_keys(tmp_path: Path) -> None:
    absolute = (tmp_path / "elsewhere" / "ledger.jsonl").as_posix()
    found = _settings(
        tmp_path,
        'plan = "plans/change-plan.yaml"\n'
        f'ledger = "{absolute}"\n'
        "[check]\n"
        'model_meta = "model.yaml"\n'
        "replicates = 500\n"
        'format = "json"\n'
        "[qc.run]\n"
        'model-version = "2.0.0"\n'
        "[demo]\n"
        'scenario = ["good-update", "qc-clean"]\n',
    )
    defaults = default_map(GROUP, found)
    check = defaults["check"]
    assert check["plan"] == str(tmp_path / "plans" / "change-plan.yaml")
    assert Path(check["ledger"]) == Path(absolute)
    assert check["model_meta"] == str(tmp_path / "model.yaml")
    assert check["replicates"] == 500
    assert check["report_format"] == "json"
    assert defaults["qc"]["run"]["model_version"] == "2.0.0"
    assert defaults["qc"]["run"]["plan"] == str(tmp_path / "plans" / "change-plan.yaml")
    assert defaults["demo"]["scenario"] == ["good-update", "qc-clean"]
    assert Path(defaults["ledger"]["verify"]["ledger"]) == Path(absolute)
    assert "version" not in defaults


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('candidat = "x"\n', "candidat is not an option of any medagentrx command"),
        ('[check]\ncandidat = "x"\n', "candidat is not an option of check"),
        ("[chek]\nseed = 1\n", r"\[chek\] is not a medagentrx command"),
        ("[qc]\nscores = 1\n", "qc.scores sets an option of a command group"),
        ("[qc.walk]\nscores = 1\n", r"\[qc.walk\] is not a medagentrx command"),
    ],
)
def test_unknown_keys_are_errors(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        default_map(GROUP, _settings(tmp_path, text))


def test_run_uses_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preds = write_table(
        tmp_path / "preds.csv", {"row_id": ["a", "b"], "y_true": [0, 1], "y_score": [0.1, 0.9]}
    )
    (tmp_path / "medagentrx.toml").write_text('[fingerprint]\ntest-preds = "preds.csv"\n', "utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "argv", ["medagentrx", "fingerprint"])
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == fingerprint_file(preds)


def test_run_reports_bad_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "medagentrx.toml").write_text('nonsense = "x"\n', "utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "argv", ["medagentrx", "version"])
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == ExitCode.USAGE_ERROR
    assert "nonsense is not an option" in capsys.readouterr().err

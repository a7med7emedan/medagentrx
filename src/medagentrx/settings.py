# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Option defaults from a settings file, so long commands stay short.

Settings are read from ``medagentrx.toml``, or from ``[tool.medagentrx]`` in
``pyproject.toml``, in the current directory. ``MEDAGENTRX_CONFIG`` names
another file, and an empty value turns settings off. Keys at the top apply to
every command with an option of that name; a table per command applies to
that command only::

    plan = "change-plan.yaml"
    ledger = "ledger.jsonl"

    [check]
    candidate = "predictions/candidate.parquet"
    out = "reports/latest"

    [qc.run]
    scores = "qc/live-scores.parquet"

Options given on the command line, and environment variables, always win.
Relative paths are relative to the settings file. Unknown keys are an error,
so a typo never goes unnoticed.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medagentrx.errors import MedAgentRxError

ENV_VAR = "MEDAGENTRX_CONFIG"
FILE_NAME = "medagentrx.toml"
MAX_SETTINGS_BYTES = 1 << 20


class SettingsError(MedAgentRxError):
    """The settings file cannot be read or names an unknown option."""


@dataclass(frozen=True)
class Settings:
    """Settings found for one run.

    Attributes:
        source: The file they came from, or None when there is none.
        values: The parsed table, before it is matched to commands.
    """

    source: Path | None
    values: Mapping[str, Any]


def find_settings(cwd: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    """Find and parse the settings that apply in ``cwd``.

    Raises:
        SettingsError: If the file is unreadable, too large or not valid TOML.
    """
    cwd = cwd or Path.cwd()
    environ = os.environ if environ is None else environ
    named = environ.get(ENV_VAR)
    if named is not None:
        if not named.strip():
            return Settings(None, {})
        path = Path(named)
        if not path.is_absolute():
            path = cwd / path
        if not path.is_file():
            raise SettingsError(f"{ENV_VAR} names {named}, which is not a file")
        return Settings(path, _table(path, tool=path.name == "pyproject.toml"))
    own = cwd / FILE_NAME
    if own.is_file():
        return Settings(own, _table(own, tool=False))
    project = cwd / "pyproject.toml"
    if project.is_file():
        table = _table(project, tool=True)
        if table:
            return Settings(project, table)
    return Settings(None, {})


def _table(path: Path, *, tool: bool) -> dict[str, Any]:
    if path.stat().st_size > MAX_SETTINGS_BYTES:
        raise SettingsError(f"{path}: settings file is larger than {MAX_SETTINGS_BYTES} bytes")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SettingsError(f"{path}: cannot be read ({exc})") from None
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: not valid TOML ({exc})") from None
    if tool:
        section = data.get("tool", {}).get("medagentrx", {})
        if not isinstance(section, dict):
            raise SettingsError(f"{path}: [tool.medagentrx] must be a table")
        return section
    return data


def _key(name: str) -> str:
    return name.lstrip("-").replace("_", "-").lower()


# Commands and parameters are Click objects; they are handled by their attributes,
# because Typer may ship its own copy of Click.


def _is_group(command: Any) -> bool:  # noqa: ANN401
    return isinstance(getattr(command, "commands", None), dict)


def _names(param: Any) -> list[str]:  # noqa: ANN401
    if getattr(param, "param_type_name", "") == "option":
        return [_key(o) for o in param.opts if o.startswith("--")]
    return [_key(param.name or "")]


def _commands(group: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:  # noqa: ANN401
    found: dict[tuple[str, ...], Any] = {}
    for name, command in group.commands.items():
        path = (*prefix, name)
        if _is_group(command):
            found.update(_commands(command, path))
        else:
            found[path] = command
    return found


def _settable(command: Any) -> dict[str, Any]:  # noqa: ANN401
    params: dict[str, Any] = {}
    for param in command.params:
        for name in _names(param):
            params[name] = param
    return params


def _value(param: Any, value: Any, base: Path) -> Any:  # noqa: ANN401
    if isinstance(value, list):
        return [_value(param, v, base) for v in value]
    if getattr(param.type, "name", "") == "path" and isinstance(value, str):
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else base / path)
    return value


def default_map(group: Any, settings: Settings) -> dict[str, Any]:  # noqa: ANN401
    """Click ``default_map`` for the command group ``group`` built from ``settings``.

    Raises:
        SettingsError: If a key matches no option, or a table no command.
    """
    if not settings.values or settings.source is None or not _is_group(group):
        return {}
    base = settings.source.parent
    commands = _commands(group)
    tables = {k: v for k, v in settings.values.items() if isinstance(v, dict)}
    shared = {k: v for k, v in settings.values.items() if not isinstance(v, dict)}
    where = str(settings.source)

    per_command: dict[tuple[str, ...], dict[str, Any]] = {}

    def walk(table: dict[str, Any], path: tuple[str, ...]) -> None:
        if path in commands:
            per_command[path] = table
            return
        if not any(c[: len(path)] == path for c in commands):
            raise SettingsError(f"{where}: [{'.'.join(path)}] is not a medagentrx command")
        for key, value in table.items():
            if not isinstance(value, dict):
                raise SettingsError(
                    f"{where}: {'.'.join((*path, key))} sets an option of a command group; "
                    "put it under one of the group's commands"
                )
            walk(value, (*path, key))

    for name, table in tables.items():
        walk(table, (name,))

    for key in shared:
        if not any(_key(key) in _settable(c) for c in commands.values()):
            raise SettingsError(f"{where}: {key} is not an option of any medagentrx command")

    result: dict[str, Any] = {}
    for path, command in commands.items():
        settable = _settable(command)
        values: dict[str, Any] = {}
        for key, value in shared.items():
            param = settable.get(_key(key))
            if param is not None and param.name:
                values[param.name] = _value(param, value, base)
        for key, value in per_command.get(path, {}).items():
            param = settable.get(_key(key))
            if param is None or not param.name:
                raise SettingsError(f"{where}: {key} is not an option of {' '.join(path)}")
            values[param.name] = _value(param, value, base)
        if values:
            node = result
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = values
    return result

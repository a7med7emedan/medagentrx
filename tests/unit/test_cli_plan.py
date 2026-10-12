# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import copy
import hashlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from medagentrx.cli import app, run
from medagentrx.exit_codes import ExitCode
from medagentrx.plan import load_plan_with_warnings
from tests.conftest import EXAMPLE_PLAN, REPO_ROOT

Data = dict[str, Any]
runner = CliRunner()


def test_validate_example_plan() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLE_PLAN)])
    assert result.exit_code == ExitCode.ACCEPTED
    assert result.output.strip() == "valid: SEPSIS-RISK-PCCP revision 3"


def test_validate_verbose_prints_fingerprint() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLE_PLAN), "--verbose"])
    assert result.exit_code == 0
    assert "plan fingerprint: " in result.output


def _set(path: str, value: object) -> Callable[[Data], None]:
    def mutate(data: Data) -> None:
        *parents, last = path.split(".")
        node: Any = data
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(last) if last.isdigit() else last] = value

    return mutate


def _delete(path: str) -> Callable[[Data], None]:
    def mutate(data: Data) -> None:
        *parents, last = path.split(".")
        node: Any = data
        for part in parents:
            node = node[part]
        del node[last]

    return mutate


def _duplicate_modification(data: Data) -> None:
    data["modifications"].append(copy.deepcopy(data["modifications"][0]))


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_set("surprise", 1), "'surprise' was unexpected"),
        (
            _set("data_management.training_inclusion.all.0.op", "regex"),
            "data_management.training_inclusion.all[0].op: 'regex' is not one of",
        ),
        (
            _set("data_management.training_inclusion.all.2.value", ["2023-01-01"]),
            "data_management.training_inclusion.all[2]: op 'between' needs a list of exactly two",
        ),
        (_set("performance.alpha_total", 1.5), "performance.alpha_total: 1.5 is greater than"),
        (_duplicate_modification, "modifications: duplicate modification id 'M1'"),
        (_delete("plan.revision"), "plan: 'revision' is a required property"),
        (_set("plan.intended_use_sha256", "abc"), "plan.intended_use_sha256: 'abc' does not match"),
        (_set("max_updates", 0), "max_updates: 0 is less than the minimum of 1"),
        (
            _set("modifications.0.type", "new_architecture"),
            "modifications[0].type: 'new_architecture' is not one of",
        ),
        (
            _set("modifications.0.automatic", "yes"),
            "modifications[0].automatic: 'yes' is not of type 'boolean'",
        ),
    ],
)
def test_validate_malformed_plans_exit_3_with_field_name(
    example_plan_data: Data,
    write_plan: Callable[[object], Path],
    mutate: Callable[[Data], None],
    expected: str,
) -> None:
    mutate(example_plan_data)
    result = runner.invoke(app, ["validate", str(write_plan(example_plan_data))])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert expected in result.output
    assert "Traceback" not in result.output


def test_validate_reports_logic_warnings(
    example_plan_data: Data, write_plan: Callable[[object], Path]
) -> None:
    example_plan_data["data_management"]["locked_test_set"]["max_evaluations"] = 3
    result = runner.invoke(app, ["validate", str(write_plan(example_plan_data))])
    assert result.exit_code == 0
    assert "warning: data_management.locked_test_set.max_evaluations" in result.output


def test_validate_missing_file() -> None:
    result = runner.invoke(app, ["validate", "does-not-exist.yaml"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "file not found" in result.output


def test_schema_command_prints_committed_schema() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    committed = (REPO_ROOT / "schema" / "change-plan.schema.json").read_text(encoding="utf-8")
    assert result.output == committed


def test_init_defaults_writes_valid_plan(tmp_path: Path) -> None:
    out = tmp_path / "change-plan.yaml"
    result = runner.invoke(app, ["init", "--defaults", "--out", str(out)])
    assert result.exit_code == 0, result.output
    loaded = load_plan_with_warnings(out)
    assert loaded.plan.plan.id == "MY-MODEL-PCCP"
    assert "# Replace with the SHA-256" in out.read_text(encoding="utf-8")


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "change-plan.yaml"
    out.write_text("keep me", encoding="utf-8")
    result = runner.invoke(app, ["init", "--defaults", "--out", str(out)])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert out.read_text(encoding="utf-8") == "keep me"
    forced = runner.invoke(app, ["init", "--defaults", "--out", str(out), "--force"])
    assert forced.exit_code == 0
    assert out.read_text(encoding="utf-8") != "keep me"


def _answers(**given: str) -> str:
    order = [
        "plan_id",
        "device",
        "anchor",
        "authorised",
        "intended_file",
        "max_updates",
        "max_evaluations",
        "alpha",
        "threshold",
        "subgroups",
    ]
    return "\n".join(given.get(key, "") for key in order) + "\n"


def test_init_interactive_answers(tmp_path: Path) -> None:
    statement = tmp_path / "intended-use.txt"
    statement.write_text("Estimates risk. Does not diagnose.\n", encoding="utf-8")
    out = tmp_path / "plan.yaml"
    bad = runner.invoke(
        app, ["init", "--out", str(out)], input=_answers(plan_id='ICU-RISK "quoted"')
    )
    assert bad.exit_code == ExitCode.USAGE_ERROR
    assert "plan.id" in bad.output
    assert not out.exists()

    answers = _answers(
        plan_id="ICU-RISK-PCCP",
        device="ICU risk: v1 # not a comment",
        anchor="3.1.0",
        authorised="2026-05-01",
        intended_file=str(statement),
        max_updates="8",
        max_evaluations="16",
        alpha="0.04",
        threshold="0.25",
        subgroups="sex, site",
    )
    result = runner.invoke(app, ["init", "--out", str(out)], input=answers)
    assert result.exit_code == 0, result.output
    plan = load_plan_with_warnings(out).plan
    assert plan.plan.id == "ICU-RISK-PCCP"
    assert plan.plan.device == "ICU risk: v1 # not a comment"
    assert plan.plan.intended_use_sha256 == hashlib.sha256(statement.read_bytes()).hexdigest()
    assert (plan.max_updates, plan.performance.alpha_total) == (8, 0.04)
    assert plan.performance.subgroups is not None
    assert plan.performance.subgroups.by == ["sex", "site"]


def test_init_reports_warnings(tmp_path: Path) -> None:
    out = tmp_path / "plan.yaml"
    answers = _answers(max_updates="20", max_evaluations="5")
    result = runner.invoke(app, ["init", "--out", str(out)], input=answers)
    assert result.exit_code == 0, result.output
    assert "warning: data_management.locked_test_set.max_evaluations: 5 looks" in result.output


def test_entry_point_reports_bare_typer_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import typer

    def broken(**_: object) -> None:
        raise typer.TyperException("boom")

    monkeypatch.setattr("medagentrx.cli.app", broken)
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == ExitCode.USAGE_ERROR


def test_init_without_subgroups(tmp_path: Path) -> None:
    out = tmp_path / "plan.yaml"
    result = runner.invoke(app, ["init", "--out", str(out)], input=_answers(subgroups=" "))
    assert result.exit_code == 0, result.output
    assert load_plan_with_warnings(out).plan.performance.subgroups is None


def test_init_unreadable_intended_use_file(tmp_path: Path) -> None:
    out = tmp_path / "plan.yaml"
    result = runner.invoke(
        app, ["init", "--out", str(out)], input=_answers(intended_file="missing.txt")
    )
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "missing.txt: cannot be read" in result.output


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["validate"], ExitCode.USAGE_ERROR),
        (["no-such-command"], ExitCode.USAGE_ERROR),
        (["validate", str(EXAMPLE_PLAN)], ExitCode.ACCEPTED),
        ([], ExitCode.USAGE_ERROR),
    ],
)
def test_entry_point_exit_codes(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], code: ExitCode
) -> None:
    monkeypatch.setattr(sys, "argv", ["medagentrx", *argv])
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == code


def test_entry_point_abort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["medagentrx", "init", "--out", str(tmp_path / "p.yaml")])
    monkeypatch.setattr(sys, "stdin", _ClosedInput())
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == ExitCode.USAGE_ERROR


class _ClosedInput:
    def readline(self) -> str:
        raise EOFError

    def read(self, *_: object) -> str:
        raise EOFError

    def isatty(self) -> bool:
        return False


def test_validate_many_plans(
    example_plan_data: Data, write_plan: Callable[[object], Path], tmp_path: Path
) -> None:
    other = tmp_path / "other" / "change-plan.yaml"
    other.parent.mkdir()
    other.write_text(EXAMPLE_PLAN.read_text(encoding="utf-8"), encoding="utf-8")
    good = runner.invoke(app, ["validate", str(EXAMPLE_PLAN), str(other)])
    assert good.exit_code == 0
    assert good.output.count("valid: SEPSIS-RISK-PCCP revision 3") == 2
    assert f"{other}: valid" in good.output
    example_plan_data["max_updates"] = 0
    bad = runner.invoke(app, ["validate", str(EXAMPLE_PLAN), str(write_plan(example_plan_data))])
    assert bad.exit_code == ExitCode.USAGE_ERROR
    assert "valid: SEPSIS-RISK-PCCP" in bad.output
    assert "max_updates" in bad.output


def test_pre_commit_hook_definition() -> None:
    import re

    hooks = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    (hook,) = hooks
    assert hook["id"] == "medagentrx-validate"
    assert hook["entry"] == "medagentrx validate"
    pattern = re.compile(hook["files"])
    assert pattern.search("examples/sepsis-risk/change-plan.yaml")
    assert pattern.search("change-plan.prod.yml")
    assert not pattern.search("docs/plan.yaml")

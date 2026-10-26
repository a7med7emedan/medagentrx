# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Write the documentation pages that come from code.

- docs/plan-reference.md from the change-plan JSON Schema.
- docs/checks.md from the check registry.
- docs/cli-reference.md from the command-line parser.
- docs/api.md from the docstrings of the public Python API.

Run from the repository root:
    uv run python scripts/make_docs.py
CI fails if the committed pages differ from what this writes.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
from pathlib import Path
from typing import Any

import typer

from medagentrx.checks import catalogue
from medagentrx.cli import app
from medagentrx.plan import plan_json_schema

# REUSE-IgnoreStart
HEADER = (
    "<!--\nSPDX-FileCopyrightText: 2026 Ahmed Hemedan\nSPDX-License-Identifier: Apache-2.0\n-->\n\n"
)
# REUSE-IgnoreEnd
SCHEMA_URL = "https://github.com/a7med7emedan/medagentrx/blob/main/schema/change-plan.schema.json"
NOTE = "<!-- This page is written by scripts/make_docs.py. Edit the code, not this file. -->\n\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _type(schema: dict[str, Any], defs: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return f"`{schema['const']}`"
    if "enum" in schema:
        return " or ".join(f"`{v}`" for v in schema["enum"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " or ".join(_type(s, defs) for s in schema[key])
    kind = schema.get("type", "any")
    if kind == "array":
        return f"list of {_type(schema.get('items', {}), defs)}"
    limits = []
    for name, symbol in (
        ("minimum", ">="),
        ("exclusiveMinimum", ">"),
        ("maximum", "<="),
        ("exclusiveMaximum", "<"),
    ):
        if name in schema:
            limits.append(f"{symbol} {schema[name]}")
    if "pattern" in schema:
        limits.append(f"pattern `{schema['pattern']}`")
    return str(kind) + (f" ({', '.join(limits)})" if limits else "")


def _object(name: str, schema: dict[str, Any], defs: dict[str, Any]) -> list[str]:
    required = set(schema.get("required", []))
    lines = [f"## {name}", ""]
    if schema.get("description"):
        lines += [_cell(schema["description"]), ""]
    lines += ["| Key | Type | Required | Description |", "|---|---|---|---|"]
    for key, sub in schema.get("properties", {}).items():
        lines.append(
            f"| `{key}` | {_cell(_type(sub, defs))} | {'yes' if key in required else 'no'} | "
            f"{_cell(sub.get('description', ''))} |"
        )
    return [*lines, ""]


def plan_reference() -> str:
    """The change-plan reference page."""
    schema = plan_json_schema()
    defs = schema.get("$defs", {})
    lines = [
        "# Change plan reference",
        "",
        "Every key of `change-plan.yaml`. Unknown keys are an error. The same definitions are in "
        f"[`schema/change-plan.schema.json`]({SCHEMA_URL}), "
        "so editors with YAML schema support can complete and check plans as you type.",
        "",
    ]
    lines += _object("Top level", schema, defs)
    for name in sorted(defs):
        lines += _object(name, defs[name], defs)
    return HEADER + NOTE + "\n".join(lines).rstrip() + "\n"


def checks_page() -> str:
    """The checks catalogue page."""
    lines = [
        "# Checks catalogue",
        "",
        "Every check has an identifier, a family, what a failure does to the verdict, and a "
        "regulatory cross-reference. A failure marked OUTSIDE_PLAN makes the update outside the "
        "plan. Any other failure gives FAILED. Warnings never change the verdict.",
        "",
        "The PLAN, DATA, PERF, LIFE and DOC checks judge a candidate update (`medagentrx check`). "
        "The LIVE checks judge a [deployment QC](qc.md) run of the live system (`medagentrx qc "
        "run`), which is IN_CONTROL or OUTSIDE_PLAN.",
        "",
        "| Check | Family | What it checks | If it fails | Cross-reference |",
        "|---|---|---|---|---|",
    ]
    for spec in catalogue():
        lines.append(
            f"| {spec.check_id} | {spec.family.value} | {_cell(spec.title)} | "
            f"{spec.breaks.value.replace('_', ' ')} | {_cell(spec.cross_reference)} |"
        )
    lines += ["", "## Details", ""]
    for spec in catalogue():
        doc = (spec.run.__doc__ or "").strip().splitlines()[0]
        lines += [f"**{spec.check_id}: {spec.title}.** {doc}", ""]
    return HEADER + NOTE + "\n".join(lines).rstrip() + "\n"


def _param_type(param: Any) -> str:  # noqa: ANN401
    if getattr(param, "is_flag", False):
        return "flag"
    name = getattr(param.type, "name", "text")
    bounds = re.sub(r"^<\w+ |>$", "", repr(param.type)) if "range" in name else ""
    kind = {
        "path": "path",
        "integer": "integer",
        "int range": "integer",
        "float": "number",
        "float range": "number",
        "text": "text",
    }.get(name, name)
    if bounds:
        kind += f" ({bounds.replace('x', 'value')})"
    if getattr(param, "multiple", False) or getattr(param, "nargs", 1) == -1:
        kind += ", repeatable"
    return kind


def _param_default(param: Any) -> str:  # noqa: ANN401
    if param.required:
        return "required"
    default = param.default
    if default is None or default is False or default == () or default == []:
        return ""
    return f"`{default}`"


def _command_section(path: list[str], command: Any) -> list[str]:  # noqa: ANN401
    title = " ".join(["medagentrx", *path])
    pieces = command.collect_usage_pieces(typer.Context(command))
    usage = re.sub(r"\{([^}]+)\}", r"\1", " ".join(pieces))
    lines = [f"## {title}", "", "```text", f"{title} {usage}".rstrip(), "```", ""]
    help_text = inspect.cleandoc(command.help or "")
    if help_text:
        lines += [help_text, ""]
    rows = []
    for param in command.params:
        if param.name == "help":
            continue
        if param.param_type_name == "argument":
            name = f"`{(param.metavar or param.name).upper()}`"
        else:
            name = ", ".join(f"`{o}`" for o in [*param.opts, *param.secondary_opts])
        description = getattr(param, "help", None) or ""
        if getattr(param, "envvar", None):
            description += f" Environment variable `{param.envvar}`."
        rows.append(
            f"| {name} | {_param_type(param)} | {_param_default(param)} | "
            f"{_cell(description.strip())} |"
        )
    if rows:
        lines += ["| Argument or option | Type | Default | Description |", "|---|---|---|---|"]
        lines += [*rows, ""]
    return lines


def _walk(group: Any, path: list[str]) -> list[tuple[list[str], Any]]:  # noqa: ANN401
    found = []
    for name, command in group.commands.items():
        if isinstance(getattr(command, "commands", None), dict):
            found += _walk(command, [*path, name])
        else:
            found.append(([*path, name], command))
    return found


def cli_reference() -> str:
    """The command-line reference page, one section per command."""
    root = typer.main.get_command(app)
    lines = [
        "# Command-line reference",
        "",
        "Every command, argument and option, generated from the parser itself. The "
        "[command-line guide](cli.md) explains exit codes, global options, settings files and "
        "JSON output.",
        "",
        "## Global options",
        "",
        "Global options go before the command, for example `medagentrx --quiet check ...`.",
        "",
        "| Option | Description |",
        "|---|---|",
    ]
    for param in root.params:
        if param.name == "help":
            continue
        names = ", ".join(f"`{o}`" for o in param.opts)
        lines.append(f"| {names} | {_cell(getattr(param, 'help', '') or '')} |")
    lines.append("")
    for path, command in _walk(root, []):
        lines += _command_section(path, command)
    return HEADER + NOTE + "\n".join(lines).rstrip() + "\n"


_SECTION = re.compile(r"^(Args|Attributes|Raises|Returns|Example):\s*$")


def _docstring(obj: Any) -> list[str]:  # noqa: ANN401
    """Docstring in Markdown, with Google-style sections as tables."""
    text = inspect.cleandoc(inspect.getdoc(obj) or "")
    out: list[str] = []
    section: str | None = None
    entries: list[list[str]] = []

    def flush() -> None:
        nonlocal section, entries
        if section is None:
            return
        out.append(f"**{section}**")
        out.append("")
        if section in ("Args", "Attributes"):
            out.extend(["| Name | Description |", "|---|---|"])
            out.extend(f"| `{n}` | {_cell(' '.join(d))} |" for n, *d in entries)
        else:
            out.extend(f"- {' '.join(e)}" for e in entries)
        out.append("")
        section, entries = None, []

    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            flush()
            section = match.group(1)
            continue
        if section is None:
            out.append(line)
            continue
        if not line.strip():
            continue
        item = re.match(r"^    (\*{0,2}\w+)(?: \([^)]*\))?:\s*(.*)$", line)
        if item and section in ("Args", "Attributes"):
            entries.append([item.group(1), item.group(2)])
        elif re.match(r"^    \w", line) and section in ("Raises", "Returns"):
            entries.append([line.strip()])
        elif entries:
            entries[-1].append(line.strip())
    flush()
    return [*out, ""]


def _default(obj: Any, param: inspect.Parameter) -> str:  # noqa: ANN401
    if dataclasses.is_dataclass(obj) and inspect.isclass(obj):
        for item in dataclasses.fields(obj):
            if item.name == param.name and item.default_factory is not dataclasses.MISSING:
                return repr(item.default_factory())
    return repr(param.default)


def _signature(name: str, obj: Any) -> str:  # noqa: ANN401
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return name
    params: list[str] = []
    star = False
    for param in signature.parameters.values():
        if param.name == "self":
            continue
        if param.kind is param.VAR_POSITIONAL:
            star = True
        if param.kind is param.KEYWORD_ONLY and not star:
            params.append("*")
            star = True
        text = param.name
        if param.kind is param.VAR_POSITIONAL:
            text = "*" + text
        elif param.kind is param.VAR_KEYWORD:
            text = "**" + text
        if param.annotation is not param.empty:
            annotation = param.annotation
            if not isinstance(annotation, str):
                annotation = inspect.formatannotation(annotation)
            text += f": {annotation}"
        if param.default is not param.empty:
            text += f" = {_default(obj, param)}"
        params.append(text)
    if len(", ".join(params)) + len(name) <= 80:
        return f"{name}({', '.join(params)})"
    return name + "(\n    " + ",\n    ".join(params) + ",\n)"


API_OBJECTS = (
    ("Checking updates", ("medagentrx:check", "medagentrx:CheckResult", "medagentrx:Verdict")),
    ("Deployment QC", ("medagentrx:qc", "medagentrx:QcResult", "medagentrx:QcVerdict")),
    ("Agents and AutoML", ("medagentrx.guard:Guard", "medagentrx.guard:Decision")),
    (
        "Lower-level building blocks",
        (
            "medagentrx:evaluate",
            "medagentrx:Evaluation",
            "medagentrx:QcRun",
            "medagentrx:load_plan",
            "medagentrx:ChangePlan",
            "medagentrx.preflight:preflight",
            "medagentrx.preflight:Preflight",
            "medagentrx.plan.diff:diff_plans",
            "medagentrx.bundle:create_bundle",
            "medagentrx.bundle:verify_bundle",
        ),
    ),
    (
        "Errors",
        (
            "medagentrx:MedAgentRxError",
            "medagentrx:PlanError",
            "medagentrx:InputError",
            "medagentrx:StatsError",
        ),
    ),
)


def _resolve(target: str) -> tuple[str, Any]:
    import importlib

    module, name = target.split(":")
    return f"{module}.{name}", getattr(importlib.import_module(module), name)


def _members(obj: type) -> list[str]:
    lines: list[str] = []
    if dataclasses.is_dataclass(obj) or obj.__module__.startswith("pydantic"):
        return lines
    for name, member in vars(obj).items():
        if name.startswith("_"):
            continue
        if isinstance(member, property):
            summary = (inspect.getdoc(member) or "").splitlines()
            lines += [f"- `{name}` (property): {summary[0] if summary else ''}"]
        elif inspect.isfunction(member):
            lines += ["", f"#### {obj.__name__}.{name}", "", "```python"]
            lines += [_signature(name, member), "```", "", *_docstring(member)]
    return lines


def api_reference() -> str:
    """The Python API reference page."""
    lines = [
        "# Python API reference",
        "",
        "The functions and classes below are the stable Python interface. Everything the "
        "command line does is available here, with the same inputs and outputs. Import from "
        "`medagentrx` unless a different module is shown.",
        "",
    ]
    for heading, targets in API_OBJECTS:
        lines += [f"## {heading}", ""]
        for target in targets:
            qualified, obj = _resolve(target)
            kind = "class" if inspect.isclass(obj) else "function"
            lines += [f"### {qualified.removeprefix('medagentrx.')}", ""]
            if inspect.isclass(obj) and issubclass(obj, Exception):
                lines += [f"*{kind}*, a subclass of `{obj.__mro__[1].__name__}`.", ""]
            elif inspect.isclass(obj) and hasattr(obj, "model_fields"):
                lines += [
                    "*class*, a validated pydantic model. Its keys are listed in the "
                    "[change plan reference](plan-reference.md).",
                    "",
                ]
            elif inspect.isclass(obj) and issubclass(obj, str):
                values = ", ".join(f"`{m.value}`" for m in obj)  # type: ignore[attr-defined]
                lines += [f"*enumeration*: {values}.", ""]
            else:
                lines += ["```python", _signature(qualified.rsplit(".", 1)[-1], obj), "```", ""]
            lines += _docstring(obj)
            if inspect.isclass(obj) and not issubclass(obj, Exception):
                lines += _members(obj)
            lines.append("")
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return HEADER + NOTE + text.rstrip() + "\n"


def main() -> None:
    """Write every generated page."""
    docs = Path("docs")
    (docs / "plan-reference.md").write_text(plan_reference(), encoding="utf-8")
    (docs / "checks.md").write_text(checks_page(), encoding="utf-8")
    (docs / "cli-reference.md").write_text(cli_reference(), encoding="utf-8")
    (docs / "api.md").write_text(api_reference(), encoding="utf-8")


if __name__ == "__main__":
    main()

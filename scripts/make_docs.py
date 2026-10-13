# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Write the documentation pages that come from code.

- docs/plan-reference.md from the change-plan JSON Schema.
- docs/checks.md from the check registry.

Run from the repository root:
    uv run python scripts/make_docs.py
CI fails if the committed pages differ from what this writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from medagentrx.checks import catalogue
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


def main() -> None:
    """Write both pages."""
    docs = Path("docs")
    (docs / "plan-reference.md").write_text(plan_reference(), encoding="utf-8")
    (docs / "checks.md").write_text(checks_page(), encoding="utf-8")


if __name__ == "__main__":
    main()

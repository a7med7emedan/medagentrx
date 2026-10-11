# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Hardened YAML reading for plan and metadata files.

PyYAML's ``SafeLoader`` already refuses Python object tags. This loader adds:

- no anchors or aliases, which stops exponential expansion ("billion laughs");
- no duplicate mapping keys, which PyYAML would otherwise resolve silently;
- no implicit timestamps, so dates stay plain ``YYYY-MM-DD`` strings;
- only ``true`` and ``false`` are booleans, so ``yes``, ``no``, ``on`` and
  ``off`` stay strings as in YAML 1.2;
- a single document only;
- conversion to plain JSON types, rejecting NaN, infinity, binary and sets.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, ClassVar

import yaml

from medagentrx.errors import PlanError

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


_DROPPED_TAGS = frozenset({"tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool"})


class StrictSafeLoader(yaml.SafeLoader):  # type: ignore[misc]  # PyYAML ships no types
    """A ``SafeLoader`` without aliases, duplicate keys or implicit timestamps."""

    yaml_implicit_resolvers: ClassVar[dict[str, list[tuple[str, re.Pattern[str]]]]] = {
        first: [(tag, regexp) for tag, regexp in resolvers if tag not in _DROPPED_TAGS]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def compose_node(self, parent: Any, index: Any) -> Any:  # noqa: ANN401
        """Refuse aliases and anchors before composing a node."""
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None:
            line = event.start_mark.line + 1
            raise PlanError(f"line {line}: YAML anchors and aliases are not allowed")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:  # noqa: ANN401
        """Refuse a mapping that repeats a key."""
        seen: set[object] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                duplicate = key in seen
            except TypeError:
                line = key_node.start_mark.line + 1
                raise PlanError(f"line {line}: mapping keys must be plain values") from None
            if duplicate:
                line = key_node.start_mark.line + 1
                raise PlanError(f"line {line}: duplicate key '{key}'")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


StrictSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def parse_yaml(text: str, *, source: str) -> JSONValue:
    """Parse one YAML document into plain JSON-compatible values.

    Args:
        text: The YAML text.
        source: Name shown in error messages, usually the file path.

    Returns:
        The parsed document.

    Raises:
        PlanError: If the text is not acceptable YAML.
    """
    try:
        data = yaml.load(text, Loader=StrictSafeLoader)  # noqa: S506  # strict subclass of SafeLoader
    except PlanError as exc:
        raise PlanError(f"{source}: {exc.summary}") from None
    except yaml.YAMLError as exc:
        raise PlanError(f"{source}: not valid YAML", [_describe_yaml_error(exc)]) from None
    except RecursionError:
        raise PlanError(f"{source}: YAML nesting is too deep") from None
    return to_json(data, path="", source=source)


def _describe_yaml_error(exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    if mark is not None:
        return f"line {mark.line + 1}, column {mark.column + 1}: {problem}"
    return str(problem)


def to_json(value: object, *, path: str, source: str) -> JSONValue:
    """Convert parsed YAML into JSON types, rejecting values JSON cannot hold."""
    where = path or "<root>"
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PlanError(f"{source}: {where}: NaN and infinity are not allowed")
        return value
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, list):
        return [to_json(item, path=f"{path}[{i}]", source=source) for i, item in enumerate(value)]
    if isinstance(value, dict):
        out: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PlanError(f"{source}: {where}: keys must be strings, found {key!r}")
            child = f"{path}.{key}" if path else key
            out[key] = to_json(item, path=child, source=source)
        return out
    raise PlanError(f"{source}: {where}: unsupported YAML type {type(value).__name__}")

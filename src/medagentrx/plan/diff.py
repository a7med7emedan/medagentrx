# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Compare two change plans key by key.

Both plans are validated first, so the comparison is between what the plans
mean, not how their files are written: comments, key order and quoting do not
count. List items that carry an ``id``, such as modifications, are matched by
it; other lists are compared position by position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from medagentrx.plan.fingerprint import plan_fingerprint
from medagentrx.plan.models import ChangePlan

ChangeKind = Literal["added", "removed", "changed"]


@dataclass(frozen=True)
class Change:
    """One difference between two plans.

    Attributes:
        path: Dotted key path, with ``[id]`` or ``[index]`` for list items.
        kind: ``added``, ``removed`` or ``changed``.
        old: Value in the old plan, or None when added.
        new: Value in the new plan, or None when removed.
    """

    path: str
    kind: ChangeKind
    old: Any = None
    new: Any = None


@dataclass(frozen=True)
class PlanDiff:
    """Outcome of ``diff_plans``.

    Attributes:
        old_fingerprint: Fingerprint of the old plan.
        new_fingerprint: Fingerprint of the new plan.
        changes: Every difference, in key order.
    """

    old_fingerprint: str
    new_fingerprint: str
    changes: tuple[Change, ...]

    @property
    def identical(self) -> bool:
        """True when the plans mean the same."""
        return not self.changes

    @property
    def revision_unchanged(self) -> bool:
        """True when the content differs but the revision number does not."""
        return bool(self.changes) and not any(c.path == "plan.revision" for c in self.changes)

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible form."""
        return {
            "identical": self.identical,
            "old_fingerprint": self.old_fingerprint,
            "new_fingerprint": self.new_fingerprint,
            "revision_unchanged": self.revision_unchanged,
            "changes": [
                {"path": c.path, "kind": c.kind, "old": c.old, "new": c.new} for c in self.changes
            ],
        }


def diff_plans(old: ChangePlan, new: ChangePlan) -> PlanDiff:
    """Every difference between ``old`` and ``new``."""
    changes: list[Change] = []
    _walk(
        old.model_dump(mode="json", by_alias=True, exclude_none=True),
        new.model_dump(mode="json", by_alias=True, exclude_none=True),
        "",
        changes,
    )
    return PlanDiff(plan_fingerprint(old), plan_fingerprint(new), tuple(changes))


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _walk(old: Any, new: Any, path: str, out: list[Change]) -> None:  # noqa: ANN401
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            here = _join(path, str(key))
            if key not in new:
                out.append(Change(here, "removed", old=old[key]))
            elif key not in old:
                out.append(Change(here, "added", new=new[key]))
            else:
                _walk(old[key], new[key], here, out)
        return
    if isinstance(old, list) and isinstance(new, list):
        _walk_list(old, new, path, out)
        return
    if old != new:
        out.append(Change(path, "changed", old=old, new=new))


def _ids(items: list[Any]) -> list[str] | None:
    ids = [i.get("id") for i in items if isinstance(i, dict)]
    named = [i for i in ids if isinstance(i, str)]
    if len(named) != len(items) or len(set(named)) != len(named):
        return None
    return named


def _walk_list(old: list[Any], new: list[Any], path: str, out: list[Change]) -> None:
    old_ids, new_ids = _ids(old), _ids(new)
    if old_ids is not None and new_ids is not None:
        before = dict(zip(old_ids, old, strict=True))
        after = dict(zip(new_ids, new, strict=True))
        for key in list(dict.fromkeys([*old_ids, *new_ids])):
            here = f"{path}[{key}]"
            if key not in after:
                out.append(Change(here, "removed", old=before[key]))
            elif key not in before:
                out.append(Change(here, "added", new=after[key]))
            else:
                _walk(before[key], after[key], here, out)
        return
    for index in range(max(len(old), len(new))):
        here = f"{path}[{index}]"
        if index >= len(new):
            out.append(Change(here, "removed", old=old[index]))
        elif index >= len(old):
            out.append(Change(here, "added", new=new[index]))
        else:
            _walk(old[index], new[index], here, out)

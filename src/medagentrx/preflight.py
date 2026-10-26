# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Check that an update's input files are ready, before the real check.

A preflight reads every file ``medagentrx check`` would read and checks its
structure: the plan, the model metadata, the three prediction files, the
manifest and the ledger. It computes no metric, so it spends no look at the
locked test set and nothing is recorded. Run it as often as needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from medagentrx.errors import MedAgentRxError
from medagentrx.io.fingerprint import test_set_fingerprint
from medagentrx.io.limits import Limits
from medagentrx.io.manifest import load_manifest
from medagentrx.io.metadata import load_model_meta
from medagentrx.io.predictions import RowMismatchError, align, load_predictions
from medagentrx.plan import load_plan_with_warnings, plan_fingerprint
from medagentrx.plan.conditions import condition_fields

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from medagentrx.io.predictions import Predictions
    from medagentrx.plan.models import ChangePlan


@dataclass(frozen=True)
class Item:
    """One preflight step.

    Attributes:
        name: What was checked, for example ``candidate``.
        ok: True when the step found no problem.
        message: One line for people.
    """

    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class Preflight:
    """Outcome of ``preflight``.

    Attributes:
        items: Every step, in the order run.
        warnings: Plan logic warnings, which never block the check.
    """

    items: tuple[Item, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        """True when every step passed, so ``medagentrx check`` can run."""
        return all(item.ok for item in self.items)

    @property
    def exit_code(self) -> int:
        """0 ready, 1 not ready."""
        return 0 if self.ready else 1

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible form."""
        return {
            "ready": self.ready,
            "exit_code": self.exit_code,
            "items": [{"name": i.name, "ok": i.ok, "message": i.message} for i in self.items],
            "warnings": list(self.warnings),
        }


class _Steps:
    def __init__(self) -> None:
        self.items: list[Item] = []

    def ok(self, name: str, message: str) -> None:
        self.items.append(Item(name, True, message))

    def problem(self, name: str, message: str) -> None:
        self.items.append(Item(name, False, message))


def preflight(
    *,
    plan: str | Path,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    manifest: str | Path,
    model_meta: str | Path,
    ledger: str | Path | None = None,
    public_key: Ed25519PublicKey | None = None,
    limits: Limits | None = None,
) -> Preflight:
    """Check the inputs of one update without evaluating it.

    Every problem is reported, not only the first. With ``public_key``, the
    ledger head must carry a valid signature by that key.
    """
    steps = _Steps()
    try:
        loaded = load_plan_with_warnings(plan)
    except MedAgentRxError as exc:
        steps.problem("plan", str(exc))
        return Preflight(tuple(steps.items))
    change_plan = loaded.plan
    header = change_plan.plan
    steps.ok("plan", f"valid: {header.id} revision {header.revision}")
    warnings = tuple(str(w) for w in loaded.warnings)

    _model_meta(steps, change_plan, model_meta)
    _predictions(steps, change_plan, candidate, previous, anchor, limits)
    _manifest(steps, change_plan, manifest, limits)
    if ledger is not None:
        _ledger(steps, change_plan, Path(ledger), public_key)
    return Preflight(tuple(steps.items), warnings)


def _model_meta(steps: _Steps, plan: ChangePlan, path: str | Path) -> None:
    try:
        meta = load_model_meta(path)
    except MedAgentRxError as exc:
        steps.problem("model_meta", str(exc))
        return
    listed = {m.id for m in plan.modifications}
    if meta.modification_id not in listed:
        steps.problem(
            "model_meta",
            f"version {meta.version} claims modification {meta.modification_id}, which the "
            f"plan does not list (it lists {', '.join(sorted(listed))})",
        )
        return
    steps.ok(
        "model_meta",
        f"version {meta.version} replaces {meta.previous_version} "
        f"under modification {meta.modification_id}",
    )


def _predictions(
    steps: _Steps,
    plan: ChangePlan,
    candidate: str | Path,
    previous: str | Path,
    anchor: str | Path,
    limits: Limits | None,
) -> None:
    subgroups = list(plan.performance.subgroups.by) if plan.performance.subgroups else []
    keys = [k for k in plan.data_management.forbid_overlap_on if k != "row_id"]
    loaded: dict[str, Predictions] = {}
    for role, path, extra in (
        ("candidate", candidate, list(dict.fromkeys([*subgroups, *keys]))),
        ("previous", previous, []),
        ("anchor", anchor, []),
    ):
        try:
            loaded[role] = load_predictions(path, subgroup_columns=extra, limits=limits)
        except MedAgentRxError as exc:
            steps.problem(role, str(exc))
            continue
        steps.ok(role, f"{loaded[role].n:,} rows")
    cand = loaded.get("candidate")
    if cand is None:
        return
    for role in ("previous", "anchor"):
        if role in loaded:
            try:
                align(cand, loaded[role])
            except RowMismatchError as exc:
                steps.problem(f"{role}_rows", f"does not match the candidate's rows ({exc})")
            else:
                steps.ok(f"{role}_rows", "same rows and labels as the candidate")
    locked = plan.data_management.locked_test_set.sha256
    if test_set_fingerprint(cand) != locked:
        steps.problem(
            "test_set",
            "the candidate's rows and labels are not the locked test set the plan fingerprints",
        )
    else:
        steps.ok("test_set", "the candidate covers the locked test set")


def _manifest(steps: _Steps, plan: ChangePlan, path: str | Path, limits: Limits | None) -> None:
    required = condition_fields(plan.data_management.training_inclusion)
    try:
        train = load_manifest(path, required_fields=required, limits=limits)
    except MedAgentRxError as exc:
        steps.problem("manifest", str(exc))
        return
    steps.ok("manifest", f"{len(train.row_id):,} training rows")


def _ledger(
    steps: _Steps,
    plan: ChangePlan,
    path: Path,
    public_key: Ed25519PublicKey | None,
) -> None:
    from medagentrx.ledger import read_entries, summarize, verify
    from medagentrx.stats.alpha import initial_state

    if not path.exists():
        steps.ok("ledger", "not found; check will create it")
        return
    result = verify(path, public_key=public_key)
    if not result.ok:
        steps.problem("ledger", "fails verification: " + "; ".join(result.problems))
        return
    history = summarize(read_entries(path))
    if history.plan_fingerprint not in (None, plan_fingerprint(plan)):
        steps.problem(
            "ledger",
            f"was started under plan {history.plan_id} revision {history.plan_revision}, "
            "and this plan differs from it",
        )
        return
    steps.ok("ledger", f"intact, {result.entries} entries")
    looks = plan.data_management.locked_test_set.max_evaluations
    if history.looks_used >= looks:
        steps.problem("budget", f"all {looks} looks at the locked test set are used")
    elif len(history.releases) >= plan.max_updates:
        steps.problem("budget", f"all {plan.max_updates} updates allowed by the plan are released")
    else:
        state = history.alpha or initial_state(
            plan.performance.alpha_spending, plan.performance.alpha_total, plan.max_updates
        )
        if state.exhausted:
            steps.problem("budget", "the alpha budget is exhausted")
        else:
            steps.ok(
                "budget",
                f"look {history.looks_used + 1} of {looks}; "
                f"{len(history.releases)} of {plan.max_updates} updates released",
            )

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Append-only, hash-chained decision ledger.

Each line of ``ledger.jsonl`` is one JSON entry. An entry carries its
sequence number, the hash of the entry before it and its own hash: the
SHA-256 of its canonical JSON without the ``hash`` field. Editing any entry
breaks its hash and every link after it.

A separate head file, ``ledger.jsonl.head`` by default, records the number
of entries and the last hash. Removing entries from the end leaves a valid
chain but no longer matches the head. Keep the head somewhere the ledger's
writers cannot rewrite, for example as a CI artifact or in version control,
for the strongest guarantee.

Every evaluation is appended, including failed ones. Budgets read back from
the ledger therefore count every look at the locked test set and every use
of alpha, not only releases.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import time
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from medagentrx.engine import Evaluation, alpha_after, json_safe
from medagentrx.errors import InputError, MedAgentRxError
from medagentrx.history import History, Release
from medagentrx.plan.models import ChangePlan
from medagentrx.signing import key_fingerprint, load_private_key, sign_head, verify_head
from medagentrx.stats.alpha import AlphaState

LEDGER_FORMAT = 1
ENTRY_KINDS = ("evaluation", "guard")
"""``evaluation``: a formal check, which spends alpha and may release an update.
``guard``: an agent's look through the guard, which spends a test-set look only."""
GENESIS = "0" * 64
DEFAULT_MAX_LEDGER_BYTES = 200_000_000
LOCK_TIMEOUT_SECONDS = 10.0


class LedgerError(MedAgentRxError):
    """The ledger fails verification and cannot be trusted."""


def head_path_for(path: Path) -> Path:
    """Default head file of a ledger."""
    return path.with_name(path.name + ".head")


def canonical(body: dict[str, Any]) -> str:
    """Canonical JSON of an entry: sorted keys, no spaces, strict numbers."""
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def entry_hash(entry: dict[str, Any]) -> str:
    """SHA-256 of an entry without its ``hash`` field."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant {name}")


def read_entries(path: Path, *, max_bytes: int = DEFAULT_MAX_LEDGER_BYTES) -> list[dict[str, Any]]:
    """Read every entry. A missing ledger has no entries.

    Raises:
        InputError: If the path is not a regular file or is too large.
        LedgerError: If a line is not a JSON object.
    """
    if not path.exists() and not path.is_symlink():
        return []
    if path.is_symlink() or not path.is_file():
        raise InputError(f"{path}: the ledger must be a regular file, not a link or directory")
    if path.stat().st_size > max_bytes:
        raise InputError(f"{path}: larger than the limit of {max_bytes} bytes")
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                raise LedgerError(f"{path}: line {number} is empty")
            try:
                value = json.loads(line, parse_constant=_reject_constant)
            except (json.JSONDecodeError, ValueError) as exc:
                raise LedgerError(f"{path}: line {number} is not valid JSON ({exc})") from None
            if not isinstance(value, dict):
                raise LedgerError(f"{path}: line {number} is not a JSON object")
            entries.append(value)
    return entries


@dataclass(frozen=True)
class Verification:
    """Outcome of ``verify``.

    Attributes:
        ok: True when the chain and head agree.
        entries: Number of entries read.
        head: Hash of the last entry, or the genesis hash for an empty ledger.
        problems: One line per problem found.
    """

    ok: bool
    entries: int
    head: str
    problems: tuple[str, ...]


def verify(
    path: Path,
    *,
    head_path: Path | None = None,
    public_key: Ed25519PublicKey | None = None,
) -> Verification:
    """Recompute the hash chain and compare it with the recorded head.

    With ``public_key``, the head must also carry a valid signature by that key.
    """
    head_file = head_path or head_path_for(path)
    try:
        entries = read_entries(path)
    except LedgerError as exc:
        return Verification(False, 0, GENESIS, (str(exc),))
    problems: list[str] = []
    previous = GENESIS
    for index, entry in enumerate(entries):
        where = f"entry {index}"
        if entry.get("format") != LEDGER_FORMAT:
            problems.append(f"{where}: unknown format {entry.get('format')!r}")
        if entry.get("seq") != index:
            problems.append(f"{where}: sequence number is {entry.get('seq')!r}")
        if entry.get("prev_hash") != previous:
            problems.append(f"{where}: does not link to the entry before it")
        actual = entry_hash(entry)
        if entry.get("hash") != actual:
            problems.append(f"{where}: content does not match its hash")
        previous = str(entry.get("hash"))
    last = previous if entries else GENESIS
    problems += _check_head(head_file, len(entries), last, public_key)
    return Verification(not problems, len(entries), last, tuple(problems))


def _check_head(
    head_file: Path, count: int, last: str, public_key: Ed25519PublicKey | None
) -> list[str]:
    if not head_file.exists():
        return [] if count == 0 else [f"head file {head_file} is missing"]
    try:
        head = json.loads(head_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"head file {head_file} cannot be read ({exc})"]
    problems = []
    if head.get("entries") != count:
        problems.append(
            f"head records {head.get('entries')} entries but the ledger has {count}; "
            "entries may have been removed"
        )
    if head.get("head") != last:
        problems.append("head hash does not match the last entry")
    if public_key is not None:
        problem = verify_head(head, public_key)
        if problem:
            problems.append(problem)
    return problems


def summarize(entries: list[dict[str, Any]]) -> History:
    """Budgets used so far, read from verified entries."""
    if not entries:
        return History()
    first = entries[0]["plan"]
    looks = sum(1 for e in entries if e.get("touched_test_set"))
    releases = tuple(
        Release(e["candidate_version"], dt.datetime.fromisoformat(e["recorded_at"]))
        for e in entries
        if e.get("kind") == "evaluation" and e.get("verdict") == "ACCEPTED"
    )
    alpha: AlphaState | None = None
    for entry in reversed(entries):
        state = (entry.get("alpha") or {}).get("state_after")
        if state:
            alpha = AlphaState(**state)
            break
    released_predictions = {
        e["candidate_version"]: e["inputs"]["candidate"]
        for e in entries
        if e.get("kind") == "evaluation"
        and e.get("verdict") == "ACCEPTED"
        and e.get("inputs", {}).get("candidate")
    }
    return History(
        plan_id=first["id"],
        plan_revision=first["revision"],
        plan_fingerprint=first["fingerprint"],
        looks_used=looks,
        releases=releases,
        alpha=alpha,
        entries=len(entries),
        released_predictions=released_predictions,
    )


def load_history(
    path: Path,
    *,
    head_path: Path | None = None,
    public_key: Ed25519PublicKey | None = None,
) -> History:
    """Verify the ledger and return its budgets.

    Raises:
        LedgerError: If verification fails; budgets from a broken ledger are not used.
    """
    result = verify(path, head_path=head_path, public_key=public_key)
    if not result.ok:
        raise LedgerError(f"{path}: the ledger fails verification", result.problems)
    return summarize(read_entries(path))


@contextlib.contextmanager
def exclusive(path: Path) -> Iterator[None]:
    """Hold the ledger's lock, for example from reading budgets to appending.

    Without it, two evaluations could both read the same budgets and both
    spend the last look at the locked test set.
    """
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise LedgerError(
                    f"{lock} exists; another evaluation may be writing. "
                    "Remove the lock file if no evaluation is running."
                ) from None
            time.sleep(0.05)
    try:
        os.close(descriptor)
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def _metrics(evaluation: Evaluation) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with contextlib.suppress(KeyError):
        out["auc"] = evaluation.finding("PERF-001").details.get("auc")
    with contextlib.suppress(KeyError):
        test = evaluation.finding("LIFE-001").details.get("test")
        if test:
            out["vs_anchor"] = {"delta": test["delta"], "ci_lower": test["ci_lower"]}
    return {k: v for k, v in out.items() if v}


def build_entry(
    evaluation: Evaluation,
    *,
    seq: int,
    prev_hash: str,
    alpha_before: AlphaState | None = None,
    kind: str = "evaluation",
    answer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ledger entry for ``evaluation``, with its hash.

    ``alpha_before`` is the ledger's own alpha state; the evaluation's copy is
    used only for the first entry. ``answer`` records what the guard told the
    agent, on guard entries only.
    """
    if evaluation.plan_id is None or evaluation.alpha_state is None:
        raise LedgerError("an evaluation with an invalid plan is not written to the ledger")
    if kind not in ENTRY_KINDS:
        raise LedgerError(f"unknown ledger entry kind {kind!r}")
    before = alpha_before or evaluation.alpha_state
    guard = kind == "guard"
    state_after = before if guard else alpha_after(before, evaluation)
    body: dict[str, Any] = {
        "format": LEDGER_FORMAT,
        "seq": seq,
        "prev_hash": prev_hash,
        "kind": kind,
        "recorded_at": evaluation.evaluated_at.isoformat(),
        "plan": {
            "id": evaluation.plan_id,
            "revision": evaluation.plan_revision,
            "fingerprint": evaluation.plan_fingerprint,
        },
        "candidate_version": evaluation.candidate_version,
        "previous_version": evaluation.previous_version,
        "modification_id": evaluation.modification_id,
        "verdict": evaluation.verdict.value,
        "failed_checks": evaluation.failed_checks,
        "warnings": [f.check_id for f in evaluation.findings if f.status.value == "warn"],
        "touched_test_set": evaluation.touched_test_set,
        "test_fingerprint": evaluation.test_fingerprint,
        "alpha": {
            "used": None if guard else evaluation.alpha_used,
            "state_after": asdict(state_after),
        },
        "metrics": {} if guard else json_safe(_metrics(evaluation)),
        "inputs": dict(evaluation.inputs),
        "seed": evaluation.seed,
        "tool_version": evaluation.tool_version,
    }
    if answer is not None:
        if not guard:
            raise LedgerError("only guard entries record an answer")
        body["answer"] = dict(answer)
    body["hash"] = entry_hash(body)
    return body


def append(
    path: Path,
    evaluation: Evaluation,
    *,
    head_path: Path | None = None,
    already_locked: bool = False,
    kind: str = "evaluation",
    signing_key: Ed25519PrivateKey | None = None,
    answer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the ledger, then append ``evaluation`` and update the head.

    Args:
        path: The ledger.
        evaluation: The evaluation to record.
        head_path: Head file. Defaults to ``head_path_for(path)``.
        already_locked: True when the caller holds ``exclusive(path)``.
        kind: ``evaluation`` or ``guard``; see ``ENTRY_KINDS``.
        signing_key: Key that signs the new head. The existing head must then
            carry a valid signature by the same key.
        answer: What the guard told the agent; guard entries only.

    Raises:
        LedgerError: If the ledger fails verification, or changed after the
            evaluation read its budgets.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = contextlib.nullcontext() if already_locked else exclusive(path)
    with lock:
        return _append_unlocked(
            path, evaluation, head_path or head_path_for(path), kind, signing_key, answer
        )


def _append_unlocked(
    path: Path,
    evaluation: Evaluation,
    head_file: Path,
    kind: str,
    signing_key: Ed25519PrivateKey | None,
    answer: Mapping[str, Any] | None,
) -> dict[str, Any]:
    public_key = signing_key.public_key() if signing_key is not None else None
    result = verify(path, head_path=head_file, public_key=public_key)
    if not result.ok:
        raise LedgerError(
            f"{path}: refusing to append to a ledger that fails verification", result.problems
        )
    if evaluation.ledger_entries_before != result.entries:
        raise LedgerError(
            f"{path}: the ledger has {result.entries} entries but the evaluation read "
            f"{evaluation.ledger_entries_before}; evaluate again with current budgets"
        )
    history = summarize(read_entries(path))
    entry = build_entry(
        evaluation,
        seq=result.entries,
        prev_hash=result.head,
        alpha_before=history.alpha,
        kind=kind,
        answer=answer,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _write_head(head_file, result.entries + 1, entry["hash"], signing_key)
    return entry


def _write_head(
    head_file: Path, count: int, last: str, signing_key: Ed25519PrivateKey | None
) -> None:
    head: dict[str, Any] = {"entries": count, "head": last}
    if signing_key is not None:
        head["signature"] = sign_head(count, last, signing_key)
    temporary = head_file.with_name(head_file.name + ".tmp")
    temporary.write_text(json.dumps(head) + "\n", encoding="utf-8")
    temporary.replace(head_file)


def signing_policy(plan: ChangePlan | None, key_path: Path | None) -> Ed25519PrivateKey | None:
    """The key that must sign ledger heads for ``plan``, or None when heads are unsigned.

    Raises:
        InputError: If the plan pins a key and none, or a different one, is given.
    """
    required = plan.ledger_signing_key_sha256 if plan is not None else None
    if key_path is None:
        if required:
            raise InputError(
                "this plan requires signed ledger heads; pass the signing key "
                "(--signing-key or MEDAGENTRX_SIGNING_KEY)"
            )
        return None
    key = load_private_key(key_path)
    if required and key_fingerprint(key.public_key()) != required:
        raise InputError("the signing key is not the key the plan names")
    return key

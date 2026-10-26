# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Evidence bundle: the plan, the ledger and the reports in one checkable zip.

A bundle is what a reviewer, auditor or notified body is sent. It holds the
change plan and its PCCP document, the decision ledger and its head, the
public key when the head is signed, and every report found in the report
folders given. ``MANIFEST.json`` lists each file with its SHA-256 and size,
and ``bundle verify`` checks a received bundle against it without extracting
anything to disk except the ledger, which it verifies in a temporary folder.

Only an intact ledger is bundled: a ledger that fails verification is an
incident to investigate, not evidence to send.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from medagentrx import __version__
from medagentrx.errors import InputError, MedAgentRxError
from medagentrx.io.paths import resolve_input

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST = "MANIFEST.json"
README = "README.txt"
BUNDLE_FORMAT = "medagentrx-bundle/1"
MAX_BUNDLE_FILE_BYTES = 256 << 20
MAX_BUNDLE_FILES = 10_000
REPORT_SUFFIXES = frozenset({".json", ".html", ".md", ".xml", ".svg", ".png"})
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

_README_TEXT = """\
MedAgentRx evidence bundle

plan/      the change plan and the PCCP document written from it
ledger/    the hash-chained decision ledger and its head, with the public key
           when the head is signed
reports/   the reports of the evaluations and deployment QC runs
MANIFEST.json lists every file with its SHA-256 and size.

To check this bundle:
    pip install medagentrx
    medagentrx bundle verify {name}
"""


class BundleError(MedAgentRxError):
    """A bundle cannot be written, or a received bundle does not check out."""


@dataclass(frozen=True)
class BundleResult:
    """Outcome of ``create_bundle``.

    Attributes:
        path: The zip written.
        files: Files inside it, by name, with their SHA-256.
        ledger_entries: Entries in the bundled ledger.
    """

    path: Path
    files: dict[str, str]
    ledger_entries: int


@dataclass(frozen=True)
class BundleCheck:
    """Outcome of ``verify_bundle``.

    Attributes:
        ok: True when every file matches the manifest and the ledger is intact.
        files: Files checked.
        problems: One line per problem found.
        manifest: The bundle's manifest, or an empty mapping when unreadable.
    """

    ok: bool
    files: int
    problems: tuple[str, ...]
    manifest: dict[str, Any]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    real = resolve_input(path)
    size = real.stat().st_size
    if size > MAX_BUNDLE_FILE_BYTES:
        raise BundleError(f"{path}: {size} bytes is more than a bundle file may hold")
    return real.read_bytes()


def _report_files(folder: Path) -> list[Path]:
    if folder.is_symlink() or not folder.is_dir():
        raise InputError(f"{folder}: not a folder of reports")
    found = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix not in REPORT_SUFFIXES:
            continue
        found.append(path)
    return found


def create_bundle(
    *,
    plan: str | Path,
    ledger: str | Path,
    out: str | Path,
    reports: tuple[str | Path, ...] = (),
    public_key_file: str | Path | None = None,
    now: dt.datetime | None = None,
) -> BundleResult:
    """Write an evidence bundle.

    Raises:
        PlanError: If the plan is not valid.
        BundleError: If the ledger fails verification or a file is too large.
        InputError: If a file or report folder cannot be read.
    """
    from medagentrx.document import to_html, to_markdown
    from medagentrx.ledger import head_path_for, verify
    from medagentrx.plan import load_plan, plan_fingerprint
    from medagentrx.render_plan import build_document
    from medagentrx.signing import key_fingerprint, load_public_key

    now = now or dt.datetime.now(dt.UTC)
    plan_path, ledger_path, out_path = Path(plan), Path(ledger), Path(out)
    change_plan = load_plan(plan_path)
    key: Ed25519PublicKey | None = None
    if public_key_file is not None:
        key = load_public_key(Path(public_key_file))
    pinned = change_plan.ledger_signing_key_sha256
    if pinned is not None and (key is None or key_fingerprint(key) != pinned):
        raise BundleError(
            "the plan pins a ledger signing key; give its public key with --public-key"
        )
    result = verify(ledger_path, public_key=key)
    if not result.ok:
        raise BundleError(
            f"{ledger_path}: the ledger fails verification, so it is not bundled",
            result.problems,
        )

    members: dict[str, bytes] = {}
    members[f"plan/{plan_path.name}"] = _read(plan_path)
    document = build_document(change_plan)
    members["plan/pccp-document.md"] = to_markdown(document).encode("utf-8")
    members["plan/pccp-document.html"] = to_html(document).encode("utf-8")
    members[f"ledger/{ledger_path.name}"] = _read(ledger_path)
    head = head_path_for(ledger_path)
    if head.exists():
        members[f"ledger/{head.name}"] = _read(head)
    if public_key_file is not None:
        members[f"ledger/{Path(public_key_file).name}"] = _read(Path(public_key_file))
    for index, folder in enumerate(reports, start=1):
        root = Path(folder)
        label = f"reports/{index:02d}-{root.name or 'reports'}"
        for path in _report_files(root):
            name = f"{label}/{path.relative_to(root).as_posix()}"
            members[name] = _read(path)
    if len(members) > MAX_BUNDLE_FILES:
        raise BundleError(f"a bundle holds at most {MAX_BUNDLE_FILES} files")

    files = {name: _sha256(data) for name, data in sorted(members.items())}
    manifest = {
        "format": BUNDLE_FORMAT,
        "created_at": now.isoformat(),
        "tool_version": __version__,
        "plan": {
            "id": change_plan.plan.id,
            "revision": change_plan.plan.revision,
            "fingerprint": plan_fingerprint(change_plan),
        },
        "ledger": {
            "file": f"ledger/{ledger_path.name}",
            "entries": result.entries,
            "head": result.head,
            "signature_checked": key is not None,
        },
        "files": [
            {"name": name, "sha256": files[name], "bytes": len(members[name])} for name in files
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_symlink():
        raise BundleError(f"{out_path}: refusing to write through a symbolic link")
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            _write(archive, name, members[name])
        _write(archive, MANIFEST, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        _write(archive, README, _README_TEXT.format(name=out_path.name).encode("utf-8"))
    return BundleResult(out_path, files, result.entries)


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def _safe_name(name: str) -> bool:
    pure = PurePosixPath(name)
    return bool(name) and not pure.is_absolute() and ".." not in pure.parts and "\\" not in name


def verify_bundle(path: str | Path, *, public_key: Ed25519PublicKey | None = None) -> BundleCheck:
    """Check a bundle against its manifest and verify the ledger inside it.

    Raises:
        InputError: If the file is not a readable zip.
    """
    from medagentrx.ledger import verify

    real = resolve_input(path)
    try:
        archive = zipfile.ZipFile(real)
    except zipfile.BadZipFile:
        raise InputError(f"{path}: not a zip file") from None
    problems: list[str] = []
    with archive:
        infos = {i.filename: i for i in archive.infolist() if not i.is_dir()}
        if len(infos) > MAX_BUNDLE_FILES + 2:
            return BundleCheck(False, 0, ("the bundle holds too many files",), {})
        unsafe = [n for n in infos if not _safe_name(n)]
        if unsafe:
            return BundleCheck(False, 0, (f"unsafe file name(s): {', '.join(unsafe)}",), {})
        if MANIFEST not in infos:
            return BundleCheck(False, 0, (f"{MANIFEST} is missing",), {})
        try:
            manifest = json.loads(_member(archive, infos[MANIFEST]))
        except (ValueError, BundleError) as exc:
            return BundleCheck(False, 0, (f"{MANIFEST} cannot be read ({exc})",), {})
        if not isinstance(manifest, dict) or manifest.get("format") != BUNDLE_FORMAT:
            return BundleCheck(False, 0, (f"{MANIFEST} is not a {BUNDLE_FORMAT} manifest",), {})
        listed = {str(f.get("name")): f for f in manifest.get("files", []) if isinstance(f, dict)}
        for name in sorted(set(infos) - set(listed) - {MANIFEST, README}):
            problems.append(f"{name}: in the bundle but not in the manifest")
        contents: dict[str, bytes] = {}
        for name, item in listed.items():
            if name not in infos:
                problems.append(f"{name}: listed in the manifest but missing")
                continue
            try:
                data = _member(archive, infos[name])
            except BundleError as exc:
                problems.append(f"{name}: {exc}")
                continue
            if _sha256(data) != item.get("sha256") or len(data) != item.get("bytes"):
                problems.append(f"{name}: does not match its SHA-256 in the manifest")
            contents[name] = data
    ledger_info = manifest.get("ledger") or {}
    ledger_name = str(ledger_info.get("file", ""))
    if ledger_name in contents:
        problems += _check_ledger(ledger_name, contents, ledger_info, public_key, verify)
    else:
        problems.append("the manifest names no bundled ledger")
    return BundleCheck(not problems, len(listed), tuple(problems), manifest)


def _member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    # zipfile never reads past a member's declared size, so checking it bounds memory.
    if info.file_size > MAX_BUNDLE_FILE_BYTES:
        raise BundleError("larger than a bundle file may be")
    with archive.open(info) as handle:
        return handle.read()


def _check_ledger(
    name: str,
    contents: dict[str, bytes],
    info: dict[str, Any],
    public_key: Ed25519PublicKey | None,
    verify: Any,  # noqa: ANN401
) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / PurePosixPath(name).name
        target.write_bytes(contents[name])
        head = f"{name}.head"
        if head in contents:
            Path(f"{target}.head").write_bytes(contents[head])
        result = verify(target, public_key=public_key)
    if not result.ok:
        problems += [f"ledger: {p}" for p in result.problems]
    elif result.head != info.get("head") or result.entries != info.get("entries"):
        problems.append("ledger: its head does not match the manifest")
    return problems

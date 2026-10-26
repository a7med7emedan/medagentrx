# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from medagentrx import check
from medagentrx.bundle import (
    MANIFEST,
    README,
    BundleError,
    create_bundle,
    verify_bundle,
)
from medagentrx.errors import InputError
from medagentrx.signing import generate_key_pair, key_fingerprint, load_public_key
from tests.helpers.cases import Case, make_case


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[Case, Path, Path]:
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "gov" / "ledger.jsonl"
    reports = tmp_path / "report"
    check(**case.kwargs(), ledger=ledger, out=reports, n_replicates=200, formats=["json", "md"])
    (reports / ".hidden").mkdir()
    (reports / ".hidden" / "x.json").write_text("{}", "utf-8")
    (reports / "notes.txt").write_text("not a report", "utf-8")
    return case, ledger, reports


def _rewrite(source: Path, target: Path, change: dict[str, bytes | None]) -> None:
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w") as new:
        for info in old.infolist():
            if info.filename in change:
                data = change.pop(info.filename)
                if data is not None:
                    new.writestr(info.filename, data)
            else:
                new.writestr(info.filename, old.read(info))
        for name, data in change.items():
            if data is not None:
                new.writestr(name, data)


def test_create_and_verify(evidence: tuple[Case, Path, Path], tmp_path: Path) -> None:
    case, ledger, reports = evidence
    out = tmp_path / "out" / "evidence.zip"
    result = create_bundle(plan=case.plan, ledger=ledger, out=out, reports=(reports,))
    assert result.ledger_entries == 1
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(MANIFEST))
        assert "medagentrx bundle verify evidence.zip" in archive.read(README).decode()
    assert {
        "plan/change-plan.yaml",
        "plan/pccp-document.md",
        "plan/pccp-document.html",
        "ledger/ledger.jsonl",
        "ledger/ledger.jsonl.head",
        "reports/01-report/report.json",
        "reports/01-report/summary.md",
    } <= names
    assert not any(".hidden" in n or (n.endswith(".txt") and n != README) for n in names)
    assert manifest["ledger"]["entries"] == 1
    assert manifest["ledger"]["signature_checked"] is False
    assert {f["name"] for f in manifest["files"]} == set(result.files)
    checked = verify_bundle(out)
    assert checked.ok, checked.problems
    assert checked.files == len(result.files)


def test_altered_bundles_are_caught(evidence: tuple[Case, Path, Path], tmp_path: Path) -> None:
    case, ledger, reports = evidence
    good = tmp_path / "good.zip"
    create_bundle(plan=case.plan, ledger=ledger, out=good, reports=(reports,))
    cases: dict[str, tuple[dict[str, bytes | None], str]] = {
        "changed": ({"plan/change-plan.yaml": b"edited"}, "does not match its SHA-256"),
        "added": ({"extra.json": b"{}"}, "in the bundle but not in the manifest"),
        "removed": ({"reports/01-report/summary.md": None}, "listed in the manifest but missing"),
        "headless": ({"ledger/ledger.jsonl.head": None}, "ledger: "),
    }
    for label, (change, message) in cases.items():
        bad = tmp_path / f"{label}.zip"
        _rewrite(good, bad, dict(change))
        result = verify_bundle(bad)
        assert not result.ok
        assert any(message in p for p in result.problems), (label, result.problems)


def test_altered_ledger_inside_a_consistent_manifest(
    evidence: tuple[Case, Path, Path], tmp_path: Path
) -> None:
    case, ledger, _ = evidence
    good = tmp_path / "good.zip"
    create_bundle(plan=case.plan, ledger=ledger, out=good)
    with zipfile.ZipFile(good) as archive:
        manifest = json.loads(archive.read(MANIFEST))
        text = archive.read("ledger/ledger.jsonl").replace(b"ACCEPTED", b"FAILED")
    for item in manifest["files"]:
        if item["name"] == "ledger/ledger.jsonl":
            item["sha256"] = hashlib.sha256(text).hexdigest()
            item["bytes"] = len(text)
    bad = tmp_path / "bad.zip"
    _rewrite(
        good,
        bad,
        {"ledger/ledger.jsonl": text, MANIFEST: json.dumps(manifest).encode()},
    )
    result = verify_bundle(bad)
    assert not result.ok
    assert any(p.startswith("ledger:") for p in result.problems)

    manifest["ledger"]["head"] = "0" * 64
    for item in manifest["files"]:
        if item["name"] == "ledger/ledger.jsonl":
            item["sha256"] = hashlib.sha256(
                zipfile.ZipFile(good).read("ledger/ledger.jsonl")
            ).hexdigest()
            item["bytes"] = len(zipfile.ZipFile(good).read("ledger/ledger.jsonl"))
    wrong_head = tmp_path / "head.zip"
    _rewrite(good, wrong_head, {MANIFEST: json.dumps(manifest).encode()})
    assert "ledger: its head does not match the manifest" in verify_bundle(wrong_head).problems


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({MANIFEST: None}, "MANIFEST.json is missing"),
        ({MANIFEST: b"not json"}, "cannot be read"),
        ({MANIFEST: b'{"format": "other"}'}, "is not a medagentrx-bundle/1 manifest"),
        ({"../escape.txt": b"x"}, "unsafe file name"),
    ],
)
def test_malformed_bundles(
    evidence: tuple[Case, Path, Path], tmp_path: Path, change: dict[str, bytes | None], message: str
) -> None:
    case, ledger, _ = evidence
    good = tmp_path / "good.zip"
    create_bundle(plan=case.plan, ledger=ledger, out=good)
    bad = tmp_path / "bad.zip"
    _rewrite(good, bad, dict(change))
    result = verify_bundle(bad)
    assert not result.ok
    assert message in result.problems[0]


def test_manifest_without_ledger(evidence: tuple[Case, Path, Path], tmp_path: Path) -> None:
    case, ledger, _ = evidence
    good = tmp_path / "good.zip"
    create_bundle(plan=case.plan, ledger=ledger, out=good)
    with zipfile.ZipFile(good) as archive:
        manifest = json.loads(archive.read(MANIFEST))
    manifest["ledger"]["file"] = "ledger/other.jsonl"
    bad = tmp_path / "bad.zip"
    _rewrite(good, bad, {MANIFEST: json.dumps(manifest).encode()})
    assert verify_bundle(bad).problems == ("the manifest names no bundled ledger",)


def test_oversized_members(
    evidence: tuple[Case, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, ledger, _ = evidence
    good = tmp_path / "good.zip"
    create_bundle(plan=case.plan, ledger=ledger, out=good)
    with zipfile.ZipFile(good) as archive:
        manifest_size = archive.getinfo(MANIFEST).file_size
    monkeypatch.setattr("medagentrx.bundle.MAX_BUNDLE_FILE_BYTES", manifest_size)
    result = verify_bundle(good)
    assert "plan/pccp-document.html: larger than a bundle file may be" in result.problems
    monkeypatch.setattr("medagentrx.bundle.MAX_BUNDLE_FILE_BYTES", manifest_size - 1)
    assert "cannot be read" in verify_bundle(good).problems[0]
    monkeypatch.setattr("medagentrx.bundle.MAX_BUNDLE_FILE_BYTES", 600)
    with pytest.raises(BundleError, match="more than a bundle file may hold"):
        create_bundle(plan=case.plan, ledger=ledger, out=tmp_path / "big.zip")
    monkeypatch.setattr("medagentrx.bundle.MAX_BUNDLE_FILES", 2)
    monkeypatch.setattr("medagentrx.bundle.MAX_BUNDLE_FILE_BYTES", 1 << 20)
    with pytest.raises(BundleError, match="at most 2 files"):
        create_bundle(plan=case.plan, ledger=ledger, out=tmp_path / "many.zip")
    assert verify_bundle(good).problems == ("the bundle holds too many files",)


def test_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / "x.zip"
    path.write_text("plain", "utf-8")
    with pytest.raises(InputError, match="not a zip file"):
        verify_bundle(path)


def test_broken_ledger_is_not_bundled(evidence: tuple[Case, Path, Path], tmp_path: Path) -> None:
    case, ledger, _ = evidence
    ledger.write_text(ledger.read_text("utf-8").replace("ACCEPTED", "FAILED"), "utf-8")
    with pytest.raises(BundleError, match="fails verification"):
        create_bundle(plan=case.plan, ledger=ledger, out=tmp_path / "e.zip")


def test_missing_report_folder(evidence: tuple[Case, Path, Path], tmp_path: Path) -> None:
    case, ledger, _ = evidence
    with pytest.raises(InputError, match="not a folder of reports"):
        create_bundle(
            plan=case.plan, ledger=ledger, out=tmp_path / "e.zip", reports=(tmp_path / "nope",)
        )


def test_signed_ledger(tmp_path: Path) -> None:
    generate_key_pair(tmp_path / "k.key", tmp_path / "k.pub")
    fingerprint = key_fingerprint(load_public_key(tmp_path / "k.pub"))
    case = make_case(
        tmp_path / "case", plan_edit=lambda p: p.update(ledger_signing_key_sha256=fingerprint)
    )
    ledger = tmp_path / "ledger.jsonl"
    check(
        **case.kwargs(),
        ledger=ledger,
        out=tmp_path / "r",
        n_replicates=200,
        formats=["json"],
        signing_key=tmp_path / "k.key",
    )
    with pytest.raises(BundleError, match="give its public key"):
        create_bundle(plan=case.plan, ledger=ledger, out=tmp_path / "e.zip")
    out = tmp_path / "signed.zip"
    create_bundle(plan=case.plan, ledger=ledger, out=out, public_key_file=tmp_path / "k.pub")
    with zipfile.ZipFile(out) as archive:
        assert "ledger/k.pub" in archive.namelist()
        assert json.loads(archive.read(MANIFEST))["ledger"]["signature_checked"] is True
    key = load_public_key(tmp_path / "k.pub")
    assert verify_bundle(out, public_key=key).ok
    generate_key_pair(tmp_path / "o.key", tmp_path / "o.pub")
    other = load_public_key(tmp_path / "o.pub")
    assert not verify_bundle(out, public_key=other).ok
    assert yaml.safe_load(case.plan.read_text("utf-8"))["ledger_signing_key_sha256"]


def test_refuses_a_symlinked_target(evidence: tuple[Case, Path, Path], tmp_path: Path) -> None:
    case, ledger, _ = evidence
    target = tmp_path / "real.zip"
    target.write_text("", "utf-8")
    link = tmp_path / "link.zip"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available")
    with pytest.raises(BundleError, match="symbolic link"):
        create_bundle(plan=case.plan, ledger=ledger, out=link)

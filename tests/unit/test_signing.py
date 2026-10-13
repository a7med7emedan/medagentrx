# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from medagentrx import InputError, Verdict, check
from medagentrx.cli import app
from medagentrx.guard import Guard
from medagentrx.ledger import LedgerError, entry_hash, head_path_for, read_entries, verify
from medagentrx.signing import (
    PASSPHRASE_ENV,
    generate_key_pair,
    key_fingerprint,
    load_private_key,
    load_public_key,
    sign_head,
    verify_head,
)
from tests.helpers.cases import Case, make_case

runner = CliRunner()


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, Path, str]:
    private, public = tmp_path / "keys" / "k.key", tmp_path / "keys" / "k.pub"
    fingerprint = generate_key_pair(private, public)
    return private, public, fingerprint


def _signed_case(root: Path, fingerprint: str, **kwargs: Any) -> Case:
    def plan(p: dict[str, Any]) -> None:
        p["ledger_signing_key_sha256"] = fingerprint

    return make_case(root, plan_edit=plan, **kwargs)


def _run(case: Case, ledger: Path, out: Path, key: Path | None) -> Any:
    return check(
        **case.kwargs(), ledger=ledger, out=out, n_replicates=200, formats=["json"], signing_key=key
    )


def test_key_pair(keys: tuple[Path, Path, str]) -> None:
    private, public, fingerprint = keys
    assert private.stat().st_mode & 0o777 == 0o600
    assert key_fingerprint(load_public_key(public)) == fingerprint
    assert key_fingerprint(load_private_key(private).public_key()) == fingerprint
    with pytest.raises(InputError, match="refusing to overwrite"):
        generate_key_pair(private, public)


def test_encrypted_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PASSPHRASE_ENV, "correct horse")
    generate_key_pair(tmp_path / "a.key", tmp_path / "a.pub")
    assert b"ENCRYPTED" in (tmp_path / "a.key").read_bytes()
    load_private_key(tmp_path / "a.key")
    monkeypatch.setenv(PASSPHRASE_ENV, "wrong")
    with pytest.raises(InputError, match="cannot read the signing key"):
        load_private_key(tmp_path / "a.key")


def test_head_signatures(keys: tuple[Path, Path, str], tmp_path: Path) -> None:
    private, public, _ = keys
    key, pub = load_private_key(private), load_public_key(public)
    head: dict[str, Any] = {
        "entries": 3,
        "head": "a" * 64,
        "signature": sign_head(3, "a" * 64, key),
    }
    assert verify_head(head, pub) is None
    assert verify_head({**head, "entries": 4}, pub) == "the head signature is not valid"
    assert verify_head({"entries": 3, "head": "a" * 64}, pub) == "the head is not signed"
    other_private = tmp_path / "o.key"
    generate_key_pair(other_private, tmp_path / "o.pub")
    assert (
        verify_head(head, load_public_key(tmp_path / "o.pub"))
        == "the head was signed with a different key"
    )
    odd = {**head, "signature": {**head["signature"], "algorithm": "rsa"}}
    assert verify_head(odd, pub) == "unknown signature algorithm 'rsa'"
    junk = {**head, "signature": {**head["signature"], "value": "!!!"}}
    assert verify_head(junk, pub) == "the head signature is not valid"


def test_wrong_key_types(tmp_path: Path) -> None:
    (tmp_path / "x.pem").write_text("not a key", encoding="utf-8")
    with pytest.raises(InputError, match="cannot read the signing key"):
        load_private_key(tmp_path / "x.pem")
    with pytest.raises(InputError, match="cannot read the public key"):
        load_public_key(tmp_path / "x.pem")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    other = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "ec.key").write_bytes(
        other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (tmp_path / "ec.pub").write_bytes(
        other.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    with pytest.raises(InputError, match="not an Ed25519 private key"):
        load_private_key(tmp_path / "ec.key")
    with pytest.raises(InputError, match="not an Ed25519 public key"):
        load_public_key(tmp_path / "ec.pub")


def test_signed_ledger_end_to_end(keys: tuple[Path, Path, str], tmp_path: Path) -> None:
    private, public, fingerprint = keys
    case = _signed_case(tmp_path / "case", fingerprint)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(InputError, match="requires signed ledger heads"):
        _run(case, ledger, tmp_path / "r0", None)
    result = _run(case, ledger, tmp_path / "r1", private)
    assert result.verdict is Verdict.ACCEPTED
    head = json.loads(head_path_for(ledger).read_text(encoding="utf-8"))
    assert head["signature"]["key"] == fingerprint
    pub = load_public_key(public)
    assert verify(ledger, public_key=pub).ok

    # An attacker without the key rewrites the entry and recomputes chain and head.
    entry = read_entries(ledger)[0]
    entry["verdict"] = "FAILED"
    entry["hash"] = entry_hash(entry)
    ledger.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    head_path_for(ledger).write_text(
        json.dumps({"entries": 1, "head": entry["hash"]}), encoding="utf-8"
    )
    assert verify(ledger).ok
    assert "the head is not signed" in verify(ledger, public_key=pub).problems
    with pytest.raises(LedgerError, match="fails verification"):
        _run(case, ledger, tmp_path / "r2", private)


def test_wrong_key_for_the_plan(keys: tuple[Path, Path, str], tmp_path: Path) -> None:
    _, _, fingerprint = keys
    other = tmp_path / "other.key"
    generate_key_pair(other, tmp_path / "other.pub")
    case = _signed_case(tmp_path / "case", fingerprint)
    with pytest.raises(InputError, match="not the key the plan names"):
        _run(case, tmp_path / "ledger.jsonl", tmp_path / "r", other)


def test_signing_without_plan_requirement(keys: tuple[Path, Path, str], tmp_path: Path) -> None:
    private, public, _ = keys
    case = make_case(tmp_path / "case")
    ledger = tmp_path / "ledger.jsonl"
    _run(case, ledger, tmp_path / "r", private)
    assert verify(ledger, public_key=load_public_key(public)).ok


def test_guard_signs_heads(keys: tuple[Path, Path, str], tmp_path: Path) -> None:
    private, public, fingerprint = keys

    def plan(p: dict[str, Any]) -> None:
        p["ledger_signing_key_sha256"] = fingerprint
        p["modifications"][0]["automatic"] = True

    case = make_case(tmp_path / "case", plan_edit=plan)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(InputError, match="requires signed ledger heads"):
        Guard(case.plan, ledger, previous=case.previous)
    guard = Guard(
        case.plan, ledger, previous=case.previous, n_replicates=200, seed=0, signing_key=private
    )
    guard.submit(case.candidate, case.model_meta, manifest=case.manifest)
    assert verify(ledger, public_key=load_public_key(public)).ok


def test_cli_signing_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keygen = runner.invoke(app, ["ledger", "keygen", "--out", str(tmp_path / "k")])
    assert keygen.exit_code == 0, keygen.output
    fingerprint = keygen.output.split('"')[1]
    case = _signed_case(tmp_path / "case", fingerprint)
    ledger = tmp_path / "ledger.jsonl"
    args = [
        "check",
        str(case.plan),
        "--candidate",
        str(case.candidate),
        "--previous",
        str(case.previous),
        "--anchor",
        str(case.anchor),
        "--manifest",
        str(case.manifest),
        "--model-meta",
        str(case.model_meta),
        "--ledger",
        str(ledger),
        "--out",
        str(tmp_path / "out"),
        "--replicates",
        "200",
        "--format",
        "json",
    ]
    assert runner.invoke(app, args).exit_code == 3
    monkeypatch.setenv("MEDAGENTRX_SIGNING_KEY", str(tmp_path / "k" / "ledger-signing.key"))
    assert runner.invoke(app, args).exit_code == 0
    verified = runner.invoke(
        app,
        [
            "ledger",
            "verify",
            str(ledger),
            "--public-key",
            str(tmp_path / "k" / "ledger-signing.pub"),
        ],
    )
    assert verified.exit_code == 0
    assert "signature valid" in verified.output
    again = runner.invoke(app, ["ledger", "keygen", "--out", str(tmp_path / "k")])
    assert again.exit_code == 3
    bad = runner.invoke(
        app, ["ledger", "verify", str(ledger), "--public-key", str(tmp_path / "missing.pub")]
    )
    assert bad.exit_code == 3

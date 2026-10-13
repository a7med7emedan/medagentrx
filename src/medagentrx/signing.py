# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Ed25519 signatures on the ledger head.

A hash chain shows that entries were edited, but whoever can write both the
ledger and its head can rewrite the whole chain. Signing the head with a key
that the writer of entries does not hold closes that gap. Keep the private
key in a trusted place, such as a CI secret; publish the public key so that
anyone can verify.

A plan may pin the key by its fingerprint (``ledger_signing_key_sha256``).
Changing the key then changes the plan, which PLAN-001 catches.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from medagentrx.errors import InputError

ALGORITHM = "ed25519"
PASSPHRASE_ENV = "MEDAGENTRX_SIGNING_KEY_PASSPHRASE"  # noqa: S105  # variable name, not a secret


def key_fingerprint(public_key: Ed25519PublicKey) -> str:
    """SHA-256 of the raw public key, as 64 hex characters."""
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def _passphrase() -> bytes | None:
    value = os.environ.get(PASSPHRASE_ENV)
    return value.encode("utf-8") if value else None


def generate_key_pair(private_path: Path, public_path: Path) -> str:
    """Write a new Ed25519 key pair as PEM and return the key fingerprint.

    The private key is encrypted when ``MEDAGENTRX_SIGNING_KEY_PASSPHRASE`` is set,
    and is written with owner-only permissions.

    Raises:
        InputError: If either file already exists.
    """
    for path in (private_path, public_path):
        if path.exists() or path.is_symlink():
            raise InputError(f"{path} exists; refusing to overwrite a key")
    key = Ed25519PrivateKey.generate()
    passphrase = _passphrase()
    encryption: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase
        else serialization.NoEncryption()
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption
    )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(private_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(private_pem)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_path.write_bytes(public_pem)
    return key_fingerprint(key.public_key())


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Read an Ed25519 private key in PEM form."""
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=_passphrase())
    except (OSError, ValueError, TypeError) as exc:
        raise InputError(f"{path}: cannot read the signing key ({exc})") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise InputError(f"{path}: not an Ed25519 private key")
    return key


def load_public_key(path: Path) -> Ed25519PublicKey:
    """Read an Ed25519 public key in PEM form."""
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise InputError(f"{path}: cannot read the public key ({exc})") from None
    if not isinstance(key, Ed25519PublicKey):
        raise InputError(f"{path}: not an Ed25519 public key")
    return key


def _message(entries: int, head: str, key_id: str) -> bytes:
    body = {"ledger": "medagentrx", "entries": entries, "head": head, "key": key_id}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_head(entries: int, head: str, key: Ed25519PrivateKey) -> dict[str, Any]:
    """Signature block for a ledger head."""
    key_id = key_fingerprint(key.public_key())
    signature = key.sign(_message(entries, head, key_id))
    return {
        "algorithm": ALGORITHM,
        "key": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }


def verify_head(head: dict[str, Any], key: Ed25519PublicKey) -> str | None:
    """Return a problem with the head's signature, or None when it is valid."""
    block = head.get("signature")
    if not isinstance(block, dict):
        return "the head is not signed"
    if block.get("algorithm") != ALGORITHM:
        return f"unknown signature algorithm {block.get('algorithm')!r}"
    if block.get("key") != key_fingerprint(key):
        return "the head was signed with a different key"
    try:
        signature = base64.b64decode(str(block.get("value", "")), validate=True)
        key.verify(
            signature, _message(int(head.get("entries", -1)), str(head.get("head")), block["key"])
        )
    except (InvalidSignature, ValueError):
        return "the head signature is not valid"
    return None

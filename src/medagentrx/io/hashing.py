# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Streaming file hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_BYTES = 1 << 20


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()

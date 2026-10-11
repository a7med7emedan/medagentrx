# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import hashlib
from pathlib import Path

from medagentrx.io.hashing import CHUNK_BYTES, sha256_file


def test_sha256_file_streams_large_files(tmp_path: Path) -> None:
    data = bytes(range(256)) * (CHUNK_BYTES // 256 * 3 + 7)
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_sha256_file_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.write_bytes(b"")
    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()

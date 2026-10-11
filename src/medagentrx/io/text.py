# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Bounded reading of small UTF-8 text files such as plans and metadata."""

from __future__ import annotations

from pathlib import Path

from medagentrx.errors import InputError, MedAgentRxError


def read_text_limited(
    path: Path, *, max_bytes: int, error: type[MedAgentRxError] = InputError
) -> str:
    """Read a UTF-8 text file, refusing anything larger than ``max_bytes``."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise error(f"{path}: cannot be read ({exc.strerror})") from None
    if len(raw) > max_bytes:
        raise error(f"{path}: larger than the limit of {max_bytes} bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error(f"{path}: not UTF-8 text (byte {exc.start})") from None

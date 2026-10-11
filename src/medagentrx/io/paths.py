# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Path guards for inputs and outputs.

Inputs must be regular files. Inside the base directory, which defaults to
the working directory, a symbolic link is followed only when its target also
lies inside it. This stops a link planted in a checkout from reading files
elsewhere. Paths the user gives outside the base directory are taken as
chosen. Outputs are written only inside the chosen output directory.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath

from medagentrx.errors import InputError, MedAgentRxError


def resolve_input(
    path: str | Path,
    *,
    base: Path | None = None,
    error: type[MedAgentRxError] = InputError,
) -> Path:
    """Return the real path of an input file after the symlink and type checks.

    Args:
        path: The path given by the user.
        base: Directory symlinks may point into. Defaults to the working directory.
        error: Exception type to raise, so plan files report a ``PlanError``.

    Raises:
        MedAgentRxError: If the file is missing, not a regular file, or reached
            through a symlink that points outside ``base``.
    """
    given = Path(path)
    base_abs = Path(os.path.abspath(base or Path.cwd()))  # noqa: PTH100  # lexical on purpose
    root = base_abs.resolve()
    absolute = Path(os.path.abspath(given))  # noqa: PTH100  # lexical: links not followed yet
    for link in _symlinks_below(absolute, (base_abs, root)):
        if not link.resolve().is_relative_to(root):
            raise error(f"{given}: symbolic link {link} points outside {root}")
    if not absolute.exists():
        raise error(f"{given}: file not found")
    real = absolute.resolve()
    if not real.is_file():
        raise error(f"{given}: not a regular file")
    return real


def _symlinks_below(absolute: Path, bases: tuple[Path, ...]) -> list[Path]:
    """Symlinked components of ``absolute`` below whichever base contains it."""
    for top in bases:
        if absolute.is_relative_to(top):
            links: list[Path] = []
            current = top
            for part in absolute.relative_to(top).parts:
                current = current / part
                if current.is_symlink():
                    links.append(current)
            return links
    return []


def check_size(path: Path, *, max_bytes: int, error: type[MedAgentRxError] = InputError) -> None:
    """Refuse a file larger than ``max_bytes`` before reading it."""
    size = path.stat().st_size
    if size > max_bytes:
        raise error(f"{path}: {size} bytes is larger than the limit of {max_bytes} bytes")


def safe_output_path(out_dir: Path, name: str) -> Path:
    """Return ``out_dir / name``, refusing any name that escapes ``out_dir``.

    Raises:
        InputError: If ``name`` is absolute, contains ``..``, or the target is a symlink.
    """
    pure = PurePath(name)
    if not name or pure.is_absolute() or pure.anchor or ".." in pure.parts:
        raise InputError(f"output name {name!r} must be a plain relative path")
    root = out_dir.resolve()
    target = root / pure
    if target.is_symlink():
        raise InputError(f"{target}: refusing to write through a symbolic link")
    if not target.resolve().is_relative_to(root):
        raise InputError(f"{target}: resolves outside the output directory {root}")
    return target

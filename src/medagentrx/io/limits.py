# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Size limits applied to every input file before it is read."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_FILE_BYTES = 1_073_741_824
"""1 GiB. A prediction file of ten million rows is well under this."""

DEFAULT_MAX_ROWS = 10_000_000
"""Ten million rows per file."""


@dataclass(frozen=True)
class Limits:
    """Largest input accepted.

    Attributes:
        max_file_bytes: Largest file size in bytes.
        max_rows: Largest number of data rows in one file.
    """

    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_rows: int = DEFAULT_MAX_ROWS

    def __post_init__(self) -> None:
        if self.max_file_bytes < 1 or self.max_rows < 1:
            raise ValueError("limits must be positive")

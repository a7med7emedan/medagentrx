# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Canonical fingerprint of the locked test set.

Algorithm (format version 1):

1. Take every row's ``row_id`` and ``y_true``.
2. Sort rows by ``row_id`` in Unicode code point order.
3. Serialise each row as ``row_id``, a tab, ``y_true`` as ``0`` or ``1``,
   and a line feed.
4. Encode the text as UTF-8 and take its SHA-256 hex digest.

Row ids may not contain tabs or line breaks, so the serialisation is
unambiguous. Row order in the file, scores, subgroup columns and file format
do not change the fingerprint. Any added, removed or relabelled row does.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from medagentrx.io.limits import Limits
from medagentrx.io.predictions import Predictions, load_predictions


def test_set_fingerprint(predictions: Predictions) -> str:
    """Return the canonical fingerprint of the rows and labels in ``predictions``."""
    digest = hashlib.sha256()
    rows = sorted(zip(predictions.row_id.tolist(), predictions.y_true.tolist(), strict=True))
    for row_id, label in rows:
        digest.update(f"{row_id}\t{label}\n".encode())
    return digest.hexdigest()


def fingerprint_file(
    path: str | Path, *, limits: Limits | None = None, base: Path | None = None
) -> str:
    """Load a prediction file and return its test-set fingerprint."""
    return test_set_fingerprint(load_predictions(path, limits=limits, base=base))

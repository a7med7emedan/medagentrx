# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from medagentrx.io.fingerprint import test_set_fingerprint as fingerprint
from medagentrx.io.predictions import Predictions

row_ids = st.text(
    alphabet=st.characters(codec="utf-8", exclude_characters="\t\n\r"),
    min_size=1,
    max_size=12,
)
tables = st.dictionaries(row_ids, st.integers(0, 1), min_size=1, max_size=60)


def _predictions(rows: list[tuple[str, int]]) -> Predictions:
    return Predictions(
        source="t",
        row_id=np.array([r for r, _ in rows], dtype=np.str_),
        y_true=np.array([y for _, y in rows], dtype=np.int8),
        y_score=np.full(len(rows), 0.5),
    )


@given(tables, st.randoms(use_true_random=False))
def test_stable_under_row_order(table: dict[str, int], rng: object) -> None:
    rows = list(table.items())
    shuffled = rows[:]
    rng.shuffle(shuffled)  # type: ignore[attr-defined]
    assert fingerprint(_predictions(rows)) == fingerprint(_predictions(shuffled))


@given(tables, st.data())
def test_changes_when_a_label_flips(table: dict[str, int], data: st.DataObject) -> None:
    rows = list(table.items())
    index = data.draw(st.integers(0, len(rows) - 1))
    flipped = rows[:]
    flipped[index] = (rows[index][0], 1 - rows[index][1])
    assert fingerprint(_predictions(rows)) != fingerprint(_predictions(flipped))


@given(tables, st.data())
def test_changes_when_a_row_is_removed(table: dict[str, int], data: st.DataObject) -> None:
    rows = list(table.items())
    if len(rows) < 2:
        return
    index = data.draw(st.integers(0, len(rows) - 1))
    assert fingerprint(_predictions(rows)) != fingerprint(
        _predictions(rows[:index] + rows[index + 1 :])
    )

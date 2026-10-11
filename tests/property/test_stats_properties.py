# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from medagentrx.stats.delong import delong, paired_auc_test

sizes = st.integers(min_value=6, max_value=60)


@st.composite
def labelled_scores(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = draw(sizes)
    y = draw(arrays(np.int8, n, elements=st.integers(0, 1)))
    y[:4] = [0, 1, 0, 1]
    # A 0.1 grid keeps every transform strictly monotone in float64.
    finite = st.integers(-500, 500).map(lambda v: v / 10)
    a = draw(arrays(np.float64, n, elements=finite))
    b = draw(arrays(np.float64, n, elements=finite))
    return y, a, b


@settings(max_examples=150, deadline=None)
@given(labelled_scores(), st.sampled_from(["exp", "cube", "affine"]))
def test_auroc_invariant_to_monotone_transforms(
    data: tuple[np.ndarray, np.ndarray, np.ndarray], kind: str
) -> None:
    y, a, _ = data
    transformed = {"exp": np.exp(a / 10), "cube": a**3, "affine": 3 * a + 7}[kind]
    original = delong(y, a)
    after = delong(y, transformed)
    np.testing.assert_allclose(after.auc, original.auc, atol=1e-12)
    np.testing.assert_allclose(after.cov, original.cov, atol=1e-12)


@settings(max_examples=150, deadline=None)
@given(labelled_scores())
def test_delong_variances_are_non_negative_and_cov_is_psd(
    data: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    y, a, b = data
    result = delong(y, a, b)
    assert np.all(np.diag(result.cov) >= -1e-15)
    assert np.min(np.linalg.eigvalsh(result.cov)) >= -1e-12
    assert np.all((result.auc >= 0) & (result.auc <= 1))


@settings(max_examples=100, deadline=None)
@given(labelled_scores(), st.floats(0.0, 0.2), st.floats(0.0, 0.2))
def test_non_inferiority_is_monotone_in_margin(
    data: tuple[np.ndarray, np.ndarray, np.ndarray], m1: float, m2: float
) -> None:
    y, a, b = data
    small, large = sorted((m1, m2))
    if paired_auc_test(y, a, b, margin=small, alpha=0.025).non_inferior:
        assert paired_auc_test(y, a, b, margin=large, alpha=0.025).non_inferior

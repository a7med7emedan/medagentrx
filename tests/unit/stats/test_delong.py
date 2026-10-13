# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import math

import numpy as np
import pytest

from medagentrx.errors import StatsError
from medagentrx.stats.delong import auc_ci, auc_fast, delong, midrank, paired_auc_test


def _brute_force(y: np.ndarray, scores: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """DeLong structural components by the O(m n) definition."""
    k = len(scores)
    pos = [s[y == 1] for s in scores]
    neg = [s[y == 0] for s in scores]
    m, n = pos[0].size, neg[0].size
    v10 = np.empty((k, m))
    v01 = np.empty((k, n))
    auc = np.empty(k)
    for r in range(k):
        psi = (pos[r][:, None] > neg[r][None, :]) + 0.5 * (pos[r][:, None] == neg[r][None, :])
        auc[r] = psi.mean()
        v10[r] = psi.mean(axis=1)
        v01[r] = psi.mean(axis=0)
    cov = np.atleast_2d(np.cov(v10)) / m + np.atleast_2d(np.cov(v01)) / n
    return auc, cov


def _data(
    seed: int = 3, n: int = 150, ties: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.35).astype(int)
    a = rng.normal(y * 1.1)
    b = 0.6 * a + rng.normal(0, 0.7, n)
    if ties:
        a, b = np.round(a, 0), np.round(b, 0)
    return y, a, b


def test_midrank_averages_ties() -> None:
    x = np.array([3.0, 1.0, 3.0, 2.0, 3.0])
    assert midrank(x).tolist() == [4.0, 1.0, 4.0, 2.0, 4.0]


@pytest.mark.parametrize("ties", [False, True])
def test_matches_brute_force(ties: bool) -> None:
    y, a, b = _data(ties=ties)
    fast = delong(y, a, b)
    auc, cov = _brute_force(y, [a, b])
    np.testing.assert_allclose(fast.auc, auc, atol=1e-12)
    np.testing.assert_allclose(fast.cov, cov, atol=1e-12)
    assert (fast.n_pos, fast.n_neg) == (int(y.sum()), int((1 - y).sum()))


def test_auc_fast_agrees() -> None:
    y, a, _ = _data(ties=True)
    assert auc_fast(y.astype(np.int8), a) == pytest.approx(float(delong(y, a).auc[0]), abs=1e-12)


def test_perfect_and_inverted_scores() -> None:
    y = np.array([0, 0, 1, 1])
    assert delong(y, [0.1, 0.2, 0.8, 0.9]).auc[0] == 1.0
    assert delong(y, [0.9, 0.8, 0.2, 0.1]).auc[0] == 0.0
    assert delong(y, [0.5, 0.5, 0.5, 0.5]).auc[0] == 0.5


def test_auc_ci() -> None:
    y, a, _ = _data()
    est = auc_ci(y, a, level=0.95)
    assert est.ci_lower < est.auc < est.ci_upper
    assert est.se == pytest.approx(math.sqrt(delong(y, a).cov[0, 0]))
    assert auc_ci([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]).ci_upper == 1.0
    with pytest.raises(StatsError, match="at least two positives"):
        auc_ci([0, 0, 1], [0.1, 0.2, 0.9])
    with pytest.raises(StatsError, match="level"):
        auc_ci(y, a, level=1.5)


def test_paired_test_consistency() -> None:
    y, a, b = _data(n=400)
    t = paired_auc_test(y, a, b, margin=0.05, alpha=0.025)
    n_pos = int(y.sum())
    assert t.df == min(n_pos, y.size - n_pos) - 1
    assert t.critical > 1.959964
    assert t.delta == pytest.approx(t.auc_new - t.auc_ref)
    assert t.z == pytest.approx((t.delta + 0.05) / t.se)
    assert t.non_inferior == (t.ci_lower > -0.05)
    assert t.non_inferior == (t.p_value < 0.025)


def test_identical_models_have_zero_se() -> None:
    y, a, _ = _data()
    t = paired_auc_test(y, a, a, margin=0.02, alpha=0.025)
    assert t.se == 0.0
    assert t.non_inferior
    assert t.p_value == 0.0
    tight = paired_auc_test(y, a, a, margin=0.0, alpha=0.025)
    assert (tight.z, tight.p_value, tight.non_inferior) == (0.0, 0.5, False)


def test_zero_se_with_worse_model() -> None:
    y = np.array([0, 0, 1, 1])
    worse = paired_auc_test(y, [0.9, 0.8, 0.2, 0.1], [0.1, 0.2, 0.8, 0.9], margin=0.0, alpha=0.025)
    assert worse.delta == -1.0
    if worse.se == 0.0:
        assert worse.p_value == 1.0
        assert not worse.non_inferior


@pytest.mark.parametrize(
    ("y", "s", "message"),
    [
        ([1, 1, 1], [0.1, 0.2, 0.3], "both outcome classes"),
        ([0, 2, 1], [0.1, 0.2, 0.3], "labels must be 0 or 1"),
        ([], [], "non-empty"),
        ([0, 1, 0, 1], [0.1, float("nan"), 0.2, 0.3], "NaN"),
        ([0, 1, 0, 1], [0.1], "length 4"),
    ],
)
def test_invalid_inputs(y: list[int], s: list[float], message: str) -> None:
    with pytest.raises(StatsError, match=message):
        delong(y, s)


def test_argument_checks() -> None:
    y, a, b = _data()
    with pytest.raises(StatsError, match="at least one"):
        delong(y)
    with pytest.raises(StatsError, match="alpha"):
        paired_auc_test(y, a, b, margin=0.02, alpha=0.6)
    with pytest.raises(StatsError, match="margin"):
        paired_auc_test(y, a, b, margin=-0.1, alpha=0.025)

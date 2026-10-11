# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import math

import numpy as np
import pytest

from medagentrx.errors import StatsError
from medagentrx.stats._common import norm_ppf
from medagentrx.stats.alpha import initial_state, next_alpha, record
from medagentrx.stats.multiplicity import bonferroni, holm
from medagentrx.stats.power import analytic_power, hanley_mcneil_variance, simulated_power
from medagentrx.stats.proportions import (
    paired_proportion_test,
    tango_interval,
    tango_score,
)
from medagentrx.stats.smd import categorical_smd, numeric_smd


def test_tango_no_discordance_closed_form() -> None:
    z = norm_ppf(0.975)
    lower, upper = tango_interval(0, 0, 50, 0.95)
    assert upper == pytest.approx(z**2 / (50 + z**2), abs=1e-9)
    assert lower == pytest.approx(-(z**2) / (50 + z**2), abs=1e-9)


def test_tango_interval_properties() -> None:
    lower, upper = tango_interval(12, 4, 100, 0.95)
    assert lower < 0.08 < upper
    z = norm_ppf(0.975)
    assert tango_score(12, 4, 100, upper) == pytest.approx(-z, abs=1e-6)
    assert tango_score(12, 4, 100, lower) == pytest.approx(z, abs=1e-6)
    mirrored = tango_interval(4, 12, 100, 0.95)
    assert mirrored == pytest.approx((-upper, -lower), abs=1e-9)
    narrow = tango_interval(120, 40, 1000, 0.95)
    assert narrow[1] - narrow[0] < upper - lower


def test_tango_extremes() -> None:
    assert tango_interval(10, 0, 10, 0.95)[1] == 1.0
    assert tango_interval(0, 10, 10, 0.95)[0] == -1.0
    with pytest.raises(StatsError, match="invalid paired counts"):
        tango_interval(6, 6, 10, 0.95)


def test_paired_proportion_uses_tango_or_bootstrap() -> None:
    rng = np.random.default_rng(4)
    n = 4000
    y = (rng.random(n) < 0.2).astype(int)
    a = 1 / (1 + np.exp(-(rng.normal(y * 1.5) - 1)))
    b = np.clip(a + rng.normal(0, 0.1, n), 0, 1)
    t = paired_proportion_test(
        y, a, b, metric="sensitivity", threshold=0.3, margin=0.05, alpha=0.025
    )
    assert t.method == "tango"
    assert t.n == int(y.sum())
    assert t.delta == pytest.approx((t.n10 - t.n01) / t.n)
    assert t.ci_lower < t.delta < t.ci_upper
    assert t.non_inferior == (t.ci_lower > -0.05)
    same = paired_proportion_test(
        y, a, a, metric="specificity", threshold=0.3, margin=0.01, alpha=0.025, n_replicates=200
    )
    assert same.method == "bootstrap"
    assert (same.ci_lower, same.ci_upper) == (0.0, 0.0)
    assert same.non_inferior
    with pytest.raises(StatsError, match="margin"):
        paired_proportion_test(y, a, b, metric="sensitivity", threshold=0.3, margin=-1, alpha=0.025)


def test_holm_known_example() -> None:
    result = holm([0.01, 0.04, 0.03, 0.005], 0.05)
    assert result.rejected == (True, False, False, True)
    assert result.adjusted_p == pytest.approx((0.03, 0.06, 0.06, 0.02))
    assert result.levels == pytest.approx((0.05 / 3, 0.025, 0.025, 0.0125))
    assert holm([], 0.05).rejected == ()


def test_holm_rejects_all_when_small() -> None:
    result = holm([0.001, 0.002], 0.05)
    assert result.rejected == (True, True)
    assert result.levels == (0.025, 0.05)


def test_bonferroni() -> None:
    result = bonferroni([0.01, 0.02, 0.3], 0.06)
    assert result.rejected == (True, True, False)
    assert result.levels == (0.02, 0.02, 0.02)
    assert result.adjusted_p == pytest.approx((0.03, 0.06, 0.9))
    assert bonferroni([], 0.05).levels == ()
    with pytest.raises(StatsError, match="p-values"):
        bonferroni([1.2], 0.05)
    with pytest.raises(StatsError, match="alpha"):
        holm([0.1], 1.5)


def test_bonferroni_spending() -> None:
    state = initial_state("bonferroni", 0.05, 4)
    for _ in range(4):
        a = next_alpha(state)
        assert a == pytest.approx(0.0125)
        state = record(state, a, rejected=True)
    assert state.spent == pytest.approx(0.05)
    assert state.exhausted
    with pytest.raises(StatsError, match="exhausted"):
        next_alpha(state)


def test_alpha_investing_wealth() -> None:
    state = initial_state("alpha_investing", 0.05, 10)
    assert state.wealth == pytest.approx(0.05 * 0.95)
    a1 = next_alpha(state)
    assert a1 == pytest.approx((0.0475 / 1.0475) / 10)
    after_fail = record(state, a1, rejected=False)
    assert after_fail.wealth == pytest.approx(0.0475 - a1 / (1 - a1))
    after_win = record(state, a1, rejected=True)
    assert after_win.wealth == pytest.approx(0.0475 + 0.05)
    drained = state
    for _ in range(10):
        drained = record(drained, next_alpha(drained), rejected=False)
    assert drained.exhausted
    assert drained.wealth >= 0.0


def test_alpha_state_checks() -> None:
    with pytest.raises(StatsError, match="alpha_total"):
        initial_state("bonferroni", 1.0, 3)
    with pytest.raises(StatsError, match="max_updates"):
        initial_state("bonferroni", 0.05, 0)


def test_hanley_mcneil_variance() -> None:
    a = 0.8
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    expected = (a * (1 - a) + 49 * (q1 - a * a) + 99 * (q2 - a * a)) / (50 * 100)
    assert hanley_mcneil_variance(0.8, 50, 100) == pytest.approx(expected)
    with pytest.raises(StatsError, match="auc"):
        hanley_mcneil_variance(0.4, 10, 10)
    with pytest.raises(StatsError, match="at least 1"):
        hanley_mcneil_variance(0.8, 0, 10)


def test_analytic_power_behaviour() -> None:
    def power(margin: float, n_pos: int = 200, n_neg: int = 1500, r: float = 0.6) -> float:
        return analytic_power(
            auc=0.8, n_pos=n_pos, n_neg=n_neg, margin=margin, alpha=0.025, correlation=r
        )

    assert power(0.0) == pytest.approx(0.025)
    small, large = power(0.02), power(0.05)
    assert 0.025 < small < large < 1
    assert power(0.02, n_pos=800, n_neg=6000) > small
    with pytest.raises(StatsError, match="correlation"):
        power(0.02, r=1.0)


def test_simulated_power_agrees_roughly() -> None:
    analytic = analytic_power(
        auc=0.8, n_pos=150, n_neg=600, margin=0.04, alpha=0.025, correlation=0.75
    )
    simulated = simulated_power(
        auc=0.8,
        n_pos=150,
        n_neg=600,
        margin=0.04,
        alpha=0.025,
        score_correlation=0.8,
        n_simulations=200,
        seed=3,
    )
    assert 0.0 <= simulated <= 1.0
    assert abs(simulated - analytic) < 0.2
    with pytest.raises(StatsError, match="n_simulations"):
        simulated_power(
            auc=0.8,
            n_pos=5,
            n_neg=5,
            margin=0.04,
            alpha=0.025,
            score_correlation=0.5,
            n_simulations=0,
        )


def test_numeric_smd() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([2.0, 3.0, 4.0, 5.0])
    assert numeric_smd(a, b) == pytest.approx(-1 / math.sqrt(5 / 3))
    assert numeric_smd([1.0, 1.0], [1.0, 1.0]) == 0.0
    assert numeric_smd([1.0, 1.0], [2.0, 2.0]) == -math.inf
    with pytest.raises(StatsError, match="two values"):
        numeric_smd([1.0], [1.0, 2.0])
    with pytest.raises(StatsError, match="finite"):
        numeric_smd([1.0, float("nan")], [1.0, 2.0])


def test_categorical_smd_binary_matches_formula() -> None:
    a = ["F"] * 30 + ["M"] * 70
    b = ["F"] * 50 + ["M"] * 50
    p1, p2 = 0.7, 0.5
    expected = abs(p1 - p2) / math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / 2)
    assert categorical_smd(a, b) == pytest.approx(expected)
    assert categorical_smd(["A", "B", "C"] * 10, ["C", "B", "A"] * 10) == pytest.approx(0.0)
    assert categorical_smd(["A"], ["A"]) == 0.0
    assert categorical_smd(["A", "B", "C"] * 10, ["A"] * 20 + ["B"] * 10) > 0.1
    with pytest.raises(StatsError, match="at least one"):
        categorical_smd([], ["A"])

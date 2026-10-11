# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import pytest

from medagentrx.errors import StatsError
from medagentrx.stats.bootstrap import paired_bootstrap, stratified_indices
from medagentrx.stats.calibration import (
    binned_curve,
    calibration,
    expected_calibration_error,
    fit_logistic,
    isotonic_fit,
    logit,
)
from medagentrx.stats.delong import auc_fast, paired_auc_test
from medagentrx.stats.metrics import average_precision, brier_score, sensitivity, specificity
from medagentrx.stats.net_benefit import (
    decision_curve,
    net_benefit,
    net_benefit_difference,
    treat_all_net_benefit,
)


def _calibrated(n: int = 20000, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    p = 1 / (1 + np.exp(-rng.normal(-1.5, 1.2, n)))
    y = (rng.random(n) < p).astype(int)
    return y, p


def test_stratified_indices_keep_class_counts() -> None:
    y = np.array([1, 0, 0, 1, 0, 0, 0], dtype=np.int8)
    for idx in stratified_indices(y, 20, np.random.default_rng(0)):
        assert int(y[idx].sum()) == 2
        assert idx.size == 7


def test_bootstrap_is_reproducible_and_brackets_estimate() -> None:
    y, p = _calibrated(2000)
    q = np.clip(p + np.random.default_rng(1).normal(0, 0.05, p.size), 0, 1)

    def diff(yy: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
        return auc_fast(yy, a) - auc_fast(yy, b)

    r1 = paired_bootstrap(y, p, q, diff, n_replicates=300, seed=5)
    r2 = paired_bootstrap(y, p, q, diff, n_replicates=300, seed=5)
    assert np.array_equal(r1.replicates, r2.replicates)
    assert r1.percentile[0] < r1.estimate < r1.percentile[1]
    assert r1.bca[0] < r1.estimate < r1.bca[1]
    delong_test = paired_auc_test(y, p, q, margin=0.0, alpha=0.025)
    width_boot = r1.percentile[1] - r1.percentile[0]
    width_delong = delong_test.ci_upper - delong_test.ci_lower
    assert width_boot == pytest.approx(width_delong, rel=0.25)


def test_bca_with_constant_statistic_and_tiny_classes() -> None:
    y = np.array([1, 0, 0], dtype=np.int8)
    p = np.array([0.9, 0.1, 0.2])
    result = paired_bootstrap(y, p, p, lambda *_: 0.0, n_replicates=100, jackknife_groups=1)
    assert result.percentile == (0.0, 0.0)
    assert result.bca == (0.0, 0.0)


def test_bootstrap_argument_checks() -> None:
    y, p = _calibrated(100)
    with pytest.raises(StatsError, match="at least 100"):
        paired_bootstrap(y, p, p, lambda *_: 0.0, n_replicates=10)
    with pytest.raises(StatsError, match="level"):
        paired_bootstrap(y, p, p, lambda *_: 0.0, level=1.0)
    with pytest.raises(StatsError, match="not finite"):
        paired_bootstrap(y, p, p, lambda *_: float("nan"))


def test_calibrated_model_has_slope_one_intercept_zero() -> None:
    y, p = _calibrated()
    cal = calibration(y, p)
    assert cal.slope == pytest.approx(1.0, abs=3 * cal.slope_se)
    assert cal.intercept == pytest.approx(0.0, abs=3 * cal.intercept_se)
    assert cal.ece < 0.02
    assert cal.brier == pytest.approx(brier_score(y.astype(np.int8), p))


def test_overconfident_model_has_slope_below_one() -> None:
    y, p = _calibrated()
    sharp = 1 / (1 + np.exp(-2 * logit(p)))
    assert calibration(y, sharp).slope == pytest.approx(0.5, abs=0.05)


def test_shifted_model_has_known_intercept() -> None:
    y, p = _calibrated()
    shifted = 1 / (1 + np.exp(-(logit(p) + 0.5)))
    assert calibration(y, shifted).intercept == pytest.approx(-0.5, abs=0.06)


def test_logistic_fit_reaches_score_zero() -> None:
    y, p = _calibrated(3000)
    x = np.column_stack([np.ones(p.size), logit(p)])
    beta, cov = fit_logistic(y.astype(float), x)
    mu = 1 / (1 + np.exp(-(x @ beta)))
    np.testing.assert_allclose(x.T @ (y - mu), 0.0, atol=1e-6)
    assert np.all(np.diag(cov) > 0)


@pytest.mark.parametrize("flip", [False, True])
def test_separation_raises(flip: bool) -> None:
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    with pytest.raises(StatsError, match="separated"):
        calibration(1 - y if flip else y, p)


def test_non_convergence_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import medagentrx.stats.calibration as module

    monkeypatch.setattr(module, "MAX_ITERATIONS", 1)
    monkeypatch.setattr(module, "TOLERANCE", 0.0)
    y, p = _calibrated(500)
    with pytest.raises(StatsError, match="did not converge"):
        calibration(y, p)


def test_step_halving_recovers_from_a_far_start() -> None:
    y = np.array([1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0])
    beta, _ = fit_logistic(y, np.ones((10, 1)), offset=np.full(10, 20.0))
    assert beta[0] == pytest.approx(np.log(0.3 / 0.7) - 20.0, abs=1e-6)


def test_singular_design_raises() -> None:
    y = np.array([0.0, 1.0, 0.0, 1.0])
    x = np.column_stack([np.ones(4), np.ones(4)])
    with pytest.raises(StatsError, match="singular"):
        fit_logistic(y, x)


def test_ece_and_curve() -> None:
    y = np.array([0, 1, 0, 1], dtype=np.int8)
    p = np.array([0.5, 0.5, 0.5, 0.5])
    assert expected_calibration_error(y, p, n_bins=2) == 0.0
    curve = binned_curve(y, p, n_bins=2)
    assert curve.counts.tolist() == [2, 2]
    assert curve.observed.sum() == pytest.approx(1.0)
    with pytest.raises(StatsError, match="n_bins"):
        expected_calibration_error(y, p, n_bins=0)


def test_isotonic_fit_pools_violators() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([1.0, 3.0, 2.0, 4.0, 3.0])
    assert isotonic_fit(x, y).tolist() == [1.0, 2.5, 2.5, 3.5, 3.5]
    shuffled = np.array([3, 0, 4, 1, 2])
    np.testing.assert_allclose(isotonic_fit(x[shuffled], y[shuffled]), [3.5, 1.0, 3.5, 2.5, 2.5])
    tied = isotonic_fit(np.array([1.0, 1.0, 2.0]), np.array([0.0, 1.0, 0.0]))
    np.testing.assert_allclose(tied, [1 / 3, 1 / 3, 1 / 3])


def test_point_metrics() -> None:
    y = np.array([1, 1, 0, 0, 1], dtype=np.int8)
    s = np.array([0.9, 0.3, 0.3, 0.1, 0.6])
    assert sensitivity(y, s, 0.3) == 1.0
    assert sensitivity(y, s, 0.5) == pytest.approx(2 / 3)
    assert specificity(y, s, 0.3) == 0.5
    assert average_precision(y, np.array([0.9, 0.8, 0.7, 0.6, 0.5])) == pytest.approx(
        (1 + 1 + 3 / 5) / 3
    )


def test_net_benefit_by_hand() -> None:
    y = np.array([1, 1, 0, 0, 0, 1, 0, 0, 0, 0])
    s = np.array([0.9, 0.4, 0.5, 0.1, 0.2, 0.1, 0.05, 0.3, 0.6, 0.2])
    # t = 0.25: flagged rows 0, 1, 2, 7, 8 -> TP 2, FP 3.
    assert net_benefit(y, s, 0.25) == pytest.approx(2 / 10 - 3 / 10 * (0.25 / 0.75))
    assert treat_all_net_benefit(y, 0.25) == pytest.approx(0.3 - 0.7 / 3)
    curve = decision_curve(y, s, [0.1, 0.25])
    assert curve.model[1] == pytest.approx(net_benefit(y, s, 0.25))
    with pytest.raises(StatsError, match="threshold"):
        net_benefit(y, s, 1.0)


def test_net_benefit_difference_bootstrap() -> None:
    y, p = _calibrated(3000)
    worse = np.clip(p + np.random.default_rng(2).normal(0, 0.15, p.size), 0, 1)
    r = net_benefit_difference(y, p, worse, 0.2, n_replicates=300, seed=1)
    assert r.estimate == pytest.approx(net_benefit(y, p, 0.2) - net_benefit(y, worse, 0.2))
    assert r.percentile[0] <= r.estimate <= r.percentile[1]

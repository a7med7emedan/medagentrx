# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Power of the paired AUROC non-inferiority test.

The variance of one AUROC follows Hanley and McNeil (Radiology 1982):
V = [A(1 - A) + (n1 - 1)(Q1 - A^2) + (n0 - 1)(Q2 - A^2)] / (n1 n0),
with Q1 = A / (2 - A) and Q2 = 2 A^2 / (1 + A). The paired difference of two
models with the same expected AUROC A and correlation r between the two
estimates has variance 2 V (1 - r). Power at a true difference d is
Phi((d + margin) / SE - z(1 - alpha)).

``required_test_size`` inverts the analytic power to size a locked test set
before it is locked. ``simulated_power`` confirms the analytic value with
binormal scores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from medagentrx.errors import StatsError
from medagentrx.stats._common import check_alpha, norm_cdf, norm_ppf
from medagentrx.stats.delong import paired_auc_test


def hanley_mcneil_variance(auc: float, n_pos: int, n_neg: int) -> float:
    """Variance of an AUROC estimate by the Hanley and McNeil approximation."""
    if not 0.5 <= auc < 1.0:
        raise StatsError(f"auc must be in [0.5, 1), got {auc}")
    if n_pos < 1 or n_neg < 1:
        raise StatsError("n_pos and n_neg must be at least 1")
    q1 = auc / (2.0 - auc)
    q2 = 2.0 * auc * auc / (1.0 + auc)
    numerator = auc * (1.0 - auc) + (n_pos - 1) * (q1 - auc**2) + (n_neg - 1) * (q2 - auc**2)
    return numerator / (n_pos * n_neg)


def analytic_power(
    *,
    auc: float,
    n_pos: int,
    n_neg: int,
    margin: float,
    alpha: float,
    correlation: float,
    true_difference: float = 0.0,
) -> float:
    """Power of the paired non-inferiority test by the normal approximation."""
    check_alpha(alpha)
    if not -1.0 < correlation < 1.0:
        raise StatsError(f"correlation must be in (-1, 1), got {correlation}")
    variance = 2.0 * hanley_mcneil_variance(auc, n_pos, n_neg) * (1.0 - correlation)
    se = math.sqrt(variance)
    return norm_cdf((true_difference + margin) / se - norm_ppf(1.0 - alpha))


@dataclass(frozen=True)
class SampleSize:
    """Smallest locked test set that reaches the target power.

    Attributes:
        n: Rows in the test set.
        n_pos: Positive rows.
        n_neg: Negative rows.
        power: Analytic power at that size.
    """

    n: int
    n_pos: int
    n_neg: int
    power: float


def required_test_size(
    *,
    auc: float,
    prevalence: float,
    margin: float,
    alpha: float,
    power: float,
    correlation: float,
    true_difference: float = 0.0,
    max_rows: int = 100_000_000,
) -> SampleSize:
    """Smallest test set whose paired AUROC test reaches ``power``.

    Positives are ``prevalence`` times the rows, rounded to the nearest row.

    Raises:
        StatsError: If an argument is out of range, or the power cannot be
            reached with ``max_rows`` rows.
    """
    check_alpha(alpha)
    if not 0.0 < prevalence < 1.0:
        raise StatsError(f"prevalence must be in (0, 1), got {prevalence}")
    if not alpha < power < 1.0:
        raise StatsError(f"power must be in (alpha, 1), got {power}")
    if true_difference + margin <= 0.0:
        raise StatsError("the true difference must lie above -margin for power to grow with size")

    def size(n: int) -> SampleSize:
        n_pos = min(max(round(prevalence * n), 1), n - 1)
        achieved = analytic_power(
            auc=auc,
            n_pos=n_pos,
            n_neg=n - n_pos,
            margin=margin,
            alpha=alpha,
            correlation=correlation,
            true_difference=true_difference,
        )
        return SampleSize(n, n_pos, n - n_pos, achieved)

    low, high = 2, 2
    while size(high).power < power:
        if high >= max_rows:
            raise StatsError(f"power {power} is not reached with {max_rows} rows")
        low, high = high, min(high * 2, max_rows)
    while high - low > 1:
        middle = (low + high) // 2
        if size(middle).power >= power:
            high = middle
        else:
            low = middle
    return size(high)


def simulated_power(
    *,
    auc: float,
    n_pos: int,
    n_neg: int,
    margin: float,
    alpha: float,
    score_correlation: float,
    n_simulations: int = 200,
    seed: int = 0,
) -> float:
    """Share of simulated paired datasets in which non-inferiority is shown.

    Both models have binormal scores with the same AUROC; their scores are
    correlated with ``score_correlation`` within each row.
    """
    if n_simulations < 1:
        raise StatsError("n_simulations must be at least 1")
    rng = np.random.default_rng(seed)
    shift = math.sqrt(2.0) * norm_ppf(auc)
    cov = np.array([[1.0, score_correlation], [score_correlation, 1.0]])
    y = np.r_[np.ones(n_pos, dtype=np.int8), np.zeros(n_neg, dtype=np.int8)]
    shown = 0
    for _ in range(n_simulations):
        scores = rng.multivariate_normal([0.0, 0.0], cov, size=n_pos + n_neg)
        scores[:n_pos] += shift
        test = paired_auc_test(y, scores[:, 0], scores[:, 1], margin=margin, alpha=alpha)
        shown += int(test.non_inferior)
    return shown / n_simulations

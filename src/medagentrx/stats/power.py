# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Power of the paired AUROC non-inferiority test.

The variance of one AUROC follows Hanley and McNeil (Radiology 1982):
V = [A(1 - A) + (n1 - 1)(Q1 - A^2) + (n0 - 1)(Q2 - A^2)] / (n1 n0),
with Q1 = A / (2 - A) and Q2 = 2 A^2 / (1 + A). The paired difference of two
models with the same expected AUROC A and correlation r between the two
estimates has variance 2 V (1 - r). Power at a true difference d is
Phi((d + margin) / SE - z(1 - alpha)).

``simulated_power`` confirms the analytic value with binormal scores.
"""

from __future__ import annotations

import math

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

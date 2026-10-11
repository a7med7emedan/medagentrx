# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""AUROC with DeLong variance, and the paired non-inferiority test.

The AUROC and its covariance follow DeLong, DeLong and Clarke-Pearson
(Biometrics 1988), computed with the O(n log n) midrank algorithm of Sun and
Xu (IEEE Signal Processing Letters 2014). Ties count one half. Variances use
the unbiased (n - 1) denominators, as in the R package pROC.

Non-inferiority of a new model against a reference with margin delta:
H0: AUC_new - AUC_ref <= -delta. The statistic is
z = (estimate + delta) / SE, and H0 is rejected when z > z(1 - alpha).
The reported interval is the two-sided (1 - 2 alpha) interval, whose lower
bound exceeds -delta exactly when H0 is rejected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError
from medagentrx.stats._common import (
    FloatArray,
    as_labels,
    as_scores,
    check_alpha,
    norm_cdf,
    norm_ppf,
)


def midrank(x: FloatArray) -> FloatArray:
    """Return 1-based ranks of ``x`` with ties given their average rank."""
    _, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts).astype(np.float64)
    average = ends - (counts - 1) / 2.0
    ranks: FloatArray = average[inverse.reshape(-1)]
    return ranks


def auc_fast(y: npt.NDArray[np.int8], scores: FloatArray) -> float:
    """AUROC by the rank-sum formula, without input checks. Used inside the bootstrap."""
    ranks = midrank(scores)
    m = int(y.sum())
    n = y.size - m
    return float((ranks[y == 1].sum() - m * (m + 1) / 2.0) / (m * n))


@dataclass(frozen=True)
class AucCovariance:
    """AUROC estimates of k scores on the same rows, with their DeLong covariance.

    Attributes:
        auc: Array of k AUROC values.
        cov: k by k covariance matrix.
        n_pos: Number of positive rows.
        n_neg: Number of negative rows.
    """

    auc: FloatArray
    cov: FloatArray
    n_pos: int
    n_neg: int


def delong(y_true: npt.ArrayLike, *scores: npt.ArrayLike) -> AucCovariance:
    """Compute AUROC and DeLong covariance for one or more paired scores.

    Args:
        y_true: Labels, 0 or 1.
        *scores: One or more score arrays aligned with ``y_true``.

    Raises:
        StatsError: If a class is missing or a score array is not finite.
    """
    if not scores:
        raise StatsError("at least one score array is needed")
    y = as_labels(y_true)
    matrix = np.vstack([as_scores(s, y.size, f"scores[{i}]") for i, s in enumerate(scores)])
    pos = matrix[:, y == 1]
    neg = matrix[:, y == 0]
    m, n = pos.shape[1], neg.shape[1]
    if m < 2 or n < 2:
        raise StatsError("DeLong variance needs at least two positives and two negatives")
    k = matrix.shape[0]
    tx = np.empty((k, m))
    ty = np.empty((k, n))
    tz = np.empty((k, m + n))
    for r in range(k):
        tx[r] = midrank(pos[r])
        ty[r] = midrank(neg[r])
        tz[r] = midrank(np.concatenate([pos[r], neg[r]]))
    auc = tz[:, :m].sum(axis=1) / (m * n) - (m + 1.0) / (2.0 * n)
    v01 = (tz[:, :m] - tx) / n
    v10 = 1.0 - (tz[:, m:] - ty) / m
    sx = np.atleast_2d(np.cov(v01))
    sy = np.atleast_2d(np.cov(v10))
    cov = sx / m + sy / n
    return AucCovariance(auc=auc.astype(np.float64), cov=cov.astype(np.float64), n_pos=m, n_neg=n)


@dataclass(frozen=True)
class AucEstimate:
    """One AUROC with its DeLong standard error and two-sided interval."""

    auc: float
    se: float
    ci_lower: float
    ci_upper: float
    level: float


def auc_ci(y_true: npt.ArrayLike, scores: npt.ArrayLike, level: float = 0.95) -> AucEstimate:
    """Return the AUROC with a DeLong Wald interval, clipped to [0, 1]."""
    if not 0.0 < level < 1.0:
        raise StatsError(f"level must be in (0, 1), got {level}")
    result = delong(y_true, scores)
    auc = float(result.auc[0])
    se = math.sqrt(max(float(result.cov[0, 0]), 0.0))
    z = norm_ppf(0.5 + level / 2.0)
    return AucEstimate(
        auc=auc,
        se=se,
        ci_lower=max(0.0, auc - z * se),
        ci_upper=min(1.0, auc + z * se),
        level=level,
    )


@dataclass(frozen=True)
class PairedAucTest:
    """Result of the paired DeLong non-inferiority test.

    Attributes:
        auc_new: AUROC of the new model.
        auc_ref: AUROC of the reference model.
        delta: ``auc_new - auc_ref``.
        se: Standard error of ``delta``.
        margin: Non-inferiority margin.
        alpha: One-sided significance level.
        z: ``(delta + margin) / se``.
        p_value: One-sided p-value for H0: delta <= -margin.
        ci_lower: Lower bound of the two-sided (1 - 2 alpha) interval.
        ci_upper: Upper bound of that interval.
        non_inferior: True when H0 is rejected.
    """

    auc_new: float
    auc_ref: float
    delta: float
    se: float
    margin: float
    alpha: float
    z: float
    p_value: float
    ci_lower: float
    ci_upper: float
    non_inferior: bool


def paired_auc_test(
    y_true: npt.ArrayLike,
    scores_new: npt.ArrayLike,
    scores_ref: npt.ArrayLike,
    *,
    margin: float,
    alpha: float,
) -> PairedAucTest:
    """Paired DeLong non-inferiority test of a new model against a reference.

    Raises:
        StatsError: If inputs are invalid, or the margin is negative.
    """
    check_alpha(alpha)
    if margin < 0:
        raise StatsError(f"margin must be zero or positive, got {margin}")
    result = delong(y_true, scores_new, scores_ref)
    return paired_test_from(result, 0, 1, margin=margin, alpha=alpha)


def paired_test_from(
    result: AucCovariance, new: int, ref: int, *, margin: float, alpha: float
) -> PairedAucTest:
    """Paired non-inferiority test of score ``new`` against score ``ref`` in ``result``.

    Lets several comparisons share one DeLong computation.
    """
    check_alpha(alpha)
    if margin < 0:
        raise StatsError(f"margin must be zero or positive, got {margin}")
    auc_new, auc_ref = float(result.auc[new]), float(result.auc[ref])
    delta = auc_new - auc_ref
    var = float(result.cov[new, new] + result.cov[ref, ref] - 2.0 * result.cov[new, ref])
    se = math.sqrt(max(var, 0.0))
    z_crit = norm_ppf(1.0 - alpha)
    if se == 0.0:
        z = math.inf if delta + margin > 0 else (0.0 if delta + margin == 0 else -math.inf)
        p_value = 0.0 if delta + margin > 0 else (0.5 if delta + margin == 0 else 1.0)
    else:
        z = (delta + margin) / se
        p_value = 1.0 - norm_cdf(z)
    return PairedAucTest(
        auc_new=auc_new,
        auc_ref=auc_ref,
        delta=delta,
        se=se,
        margin=margin,
        alpha=alpha,
        z=z,
        p_value=p_value,
        ci_lower=delta - z_crit * se,
        ci_upper=delta + z_crit * se,
        non_inferior=z > z_crit,
    )

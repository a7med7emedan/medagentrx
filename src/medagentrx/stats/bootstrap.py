# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Paired stratified bootstrap with percentile and BCa intervals.

Positives and negatives are resampled separately, so every replicate keeps
the observed class counts. Both models are evaluated on the same resampled
rows, which preserves their pairing.

The BCa interval (Efron 1987) uses a bias correction from the share of
replicates below the estimate, and an acceleration from a grouped
jackknife: the rows of each class are split into ``jackknife_groups`` groups
and one group from each class is left out at a time. With one row per group
this is the ordinary jackknife; larger groups keep the cost bounded for
large test sets.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError
from medagentrx.stats._common import FloatArray, as_labels, as_scores, norm_cdf, norm_ppf

Labels = npt.NDArray[np.int8]
Statistic = Callable[[Labels, FloatArray, FloatArray], float]
"""A statistic of (labels, scores_a, scores_b), for example a paired difference."""

DEFAULT_REPLICATES = 2000
DEFAULT_JACKKNIFE_GROUPS = 200


@dataclass(frozen=True)
class BootstrapResult:
    """Point estimate and bootstrap intervals of a statistic.

    Attributes:
        estimate: Statistic on the original data.
        replicates: Statistic on each bootstrap sample.
        level: Two-sided coverage of the intervals.
        percentile: Percentile interval (lower, upper).
        bca: Bias-corrected and accelerated interval (lower, upper).
        seed: Seed used for resampling.
    """

    estimate: float
    replicates: FloatArray
    level: float
    percentile: tuple[float, float]
    bca: tuple[float, float]
    seed: int


def stratified_indices(
    y: Labels, n_replicates: int, rng: np.random.Generator
) -> Iterator[npt.NDArray[np.intp]]:
    """Yield ``n_replicates`` arrays of row indices, each resampled within each class.

    Replicates are drawn one at a time so memory stays O(n) for any B.
    """
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    for _ in range(n_replicates):
        yield np.concatenate(
            [
                pos[rng.integers(0, pos.size, size=pos.size)],
                neg[rng.integers(0, neg.size, size=neg.size)],
            ]
        )


def paired_bootstrap(
    y_true: npt.ArrayLike,
    scores_a: npt.ArrayLike,
    scores_b: npt.ArrayLike,
    statistic: Statistic,
    *,
    n_replicates: int = DEFAULT_REPLICATES,
    level: float = 0.95,
    seed: int = 0,
    jackknife_groups: int = DEFAULT_JACKKNIFE_GROUPS,
) -> BootstrapResult:
    """Bootstrap a paired statistic with stratified resampling.

    Args:
        y_true: Labels, 0 or 1.
        scores_a: Scores of the first model.
        scores_b: Scores of the second model, aligned with ``scores_a``.
        statistic: Function of (labels, scores_a, scores_b).
        n_replicates: Number of bootstrap samples, B.
        level: Two-sided coverage of the intervals.
        seed: Seed for the random generator.
        jackknife_groups: Groups per class for the BCa acceleration.

    Raises:
        StatsError: If inputs are invalid or the statistic is not finite.
    """
    if n_replicates < 100:
        raise StatsError(f"n_replicates must be at least 100, got {n_replicates}")
    if not 0.0 < level < 1.0:
        raise StatsError(f"level must be in (0, 1), got {level}")
    y = as_labels(y_true)
    a = as_scores(scores_a, y.size, "scores_a")
    b = as_scores(scores_b, y.size, "scores_b")
    estimate = _finite(statistic(y, a, b), "estimate")
    rng = np.random.default_rng(seed)
    replicates = np.array(
        [
            _finite(statistic(y[i], a[i], b[i]), "replicate")
            for i in stratified_indices(y, n_replicates, rng)
        ],
        dtype=np.float64,
    )
    tail = (1.0 - level) / 2.0
    percentile = (
        float(np.quantile(replicates, tail)),
        float(np.quantile(replicates, 1.0 - tail)),
    )
    acceleration = _acceleration(y, a, b, statistic, jackknife_groups)
    bca = _bca(replicates, estimate, acceleration, tail)
    return BootstrapResult(
        estimate=estimate,
        replicates=replicates,
        level=level,
        percentile=percentile,
        bca=bca,
        seed=seed,
    )


def _finite(value: float, what: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise StatsError(f"bootstrap statistic is not finite for the {what}")
    return value


def _acceleration(
    y: Labels, a: FloatArray, b: FloatArray, statistic: Statistic, groups: int
) -> float:
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    values: list[float] = []
    for members in (pos, neg):
        k = min(groups, members.size)
        if k < 2:
            continue
        for chunk in np.array_split(members, k):
            keep = np.setdiff1d(np.arange(y.size), chunk, assume_unique=True)
            values.append(_finite(statistic(y[keep], a[keep], b[keep]), "jackknife"))
    if len(values) < 2:
        return 0.0
    theta = np.array(values)
    diff = theta.mean() - theta
    denominator = 6.0 * math.pow(float(np.sum(diff**2)), 1.5)
    if denominator == 0.0:
        return 0.0
    return float(np.sum(diff**3)) / denominator


def _bca(
    replicates: FloatArray, estimate: float, acceleration: float, tail: float
) -> tuple[float, float]:
    below = float(np.mean(replicates < estimate)) + 0.5 * float(np.mean(replicates == estimate))
    below = min(max(below, 1.0 / (replicates.size + 1)), replicates.size / (replicates.size + 1))
    z0 = norm_ppf(below)

    def adjusted(p: float) -> float:
        z = norm_ppf(p)
        shifted = z0 + (z0 + z) / (1.0 - acceleration * (z0 + z))
        return norm_cdf(shifted)

    return (
        float(np.quantile(replicates, adjusted(tail))),
        float(np.quantile(replicates, adjusted(1.0 - tail))),
    )

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Paired difference of proportions: sensitivity or specificity at a threshold.

Within one class (positives for sensitivity, negatives for specificity), each
row is a pair: correct under the new model, correct under the reference.
Let n10 count rows correct only under the new model and n01 rows correct only
under the reference. The difference is (n10 - n01) / n.

The interval is the score interval of Tango (Statistics in Medicine 1998),
found by bisection on the score statistic with the restricted maximum
likelihood estimate of the discordant cell. When fewer than
``SPARSE_DISCORDANT`` pairs are discordant, the paired stratified bootstrap
percentile interval is used instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError
from medagentrx.stats._common import FloatArray, as_labels, as_scores, check_alpha, norm_ppf
from medagentrx.stats.bootstrap import DEFAULT_REPLICATES, Statistic, paired_bootstrap
from medagentrx.stats.metrics import Labels, predicted_positive

SPARSE_DISCORDANT = 10
BISECTION_STEPS = 200


def tango_score(n10: int, n01: int, n: int, delta: float) -> float:
    """Tango's score statistic for H0: difference = ``delta``.

    Decreasing in ``delta``. Positive when the observed difference exceeds ``delta``.
    """
    pa = 2.0 * n
    pb = -n01 - n10 + (2.0 * n - n10 + n01) * delta
    pc = -n01 * delta * (1.0 - delta)
    q = (math.sqrt(max(pb * pb - 4.0 * pa * pc, 0.0)) - pb) / (2.0 * pa)
    numerator = n10 - n01 - n * delta
    variance = n * (2.0 * q + delta * (1.0 - delta))
    if variance <= 0.0:
        return 0.0 if numerator == 0 else math.copysign(math.inf, numerator)
    return numerator / math.sqrt(variance)


def tango_interval(n10: int, n01: int, n: int, level: float) -> tuple[float, float]:
    """Two-sided Tango score interval for the paired difference (n10 - n01) / n."""
    if n < 1 or n10 < 0 or n01 < 0 or n10 + n01 > n:
        raise StatsError(f"invalid paired counts n10={n10}, n01={n01}, n={n}")
    z = norm_ppf(0.5 + level / 2.0)
    estimate = (n10 - n01) / n
    upper = _solve(n10, n01, n, -z, estimate, 1.0)
    lower = _solve(n10, n01, n, z, -1.0, estimate)
    return lower, upper


def _solve(n10: int, n01: int, n: int, target: float, low: float, high: float) -> float:
    """Find delta in [low, high] where the decreasing score equals ``target``."""
    if tango_score(n10, n01, n, high) >= target:
        return high
    if tango_score(n10, n01, n, low) <= target:
        return low
    for _ in range(BISECTION_STEPS):
        mid = 0.5 * (low + high)
        if tango_score(n10, n01, n, mid) > target:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


@dataclass(frozen=True)
class PairedProportionTest:
    """Non-inferiority of a paired proportion (sensitivity or specificity).

    Attributes:
        metric: ``sensitivity`` or ``specificity``.
        value_new: Proportion under the new model.
        value_ref: Proportion under the reference.
        delta: ``value_new - value_ref``.
        n: Rows in the class.
        n10: Rows correct only under the new model.
        n01: Rows correct only under the reference.
        margin: Non-inferiority margin.
        alpha: One-sided significance level.
        ci_lower: Lower bound of the two-sided (1 - 2 alpha) interval.
        ci_upper: Upper bound of that interval.
        method: ``tango`` or ``bootstrap``.
        non_inferior: True when the lower bound exceeds ``-margin``.
    """

    metric: Literal["sensitivity", "specificity"]
    value_new: float
    value_ref: float
    delta: float
    n: int
    n10: int
    n01: int
    margin: float
    alpha: float
    ci_lower: float
    ci_upper: float
    method: Literal["tango", "bootstrap"]
    non_inferior: bool


def paired_proportion_test(
    y_true: npt.ArrayLike,
    scores_new: npt.ArrayLike,
    scores_ref: npt.ArrayLike,
    *,
    metric: Literal["sensitivity", "specificity"],
    threshold: float,
    margin: float,
    alpha: float,
    seed: int = 0,
    n_replicates: int = DEFAULT_REPLICATES,
) -> PairedProportionTest:
    """Non-inferiority test of sensitivity or specificity at ``threshold``."""
    check_alpha(alpha)
    if margin < 0:
        raise StatsError(f"margin must be zero or positive, got {margin}")
    y = as_labels(y_true)
    new = as_scores(scores_new, y.size, "scores_new")
    ref = as_scores(scores_ref, y.size, "scores_ref")
    target = 1 if metric == "sensitivity" else 0
    members = y == target
    correct_new = predicted_positive(new[members], threshold) == bool(target)
    correct_ref = predicted_positive(ref[members], threshold) == bool(target)
    n = int(members.sum())
    n10 = int(np.sum(correct_new & ~correct_ref))
    n01 = int(np.sum(~correct_new & correct_ref))
    value_new = float(correct_new.mean())
    value_ref = float(correct_ref.mean())
    level = 1.0 - 2.0 * alpha
    if n10 + n01 >= SPARSE_DISCORDANT:
        lower, upper = tango_interval(n10, n01, n, level)
        method: Literal["tango", "bootstrap"] = "tango"
    else:
        result = paired_bootstrap(
            y,
            new,
            ref,
            _difference(metric, threshold),
            n_replicates=n_replicates,
            level=level,
            seed=seed,
        )
        lower, upper = result.percentile
        method = "bootstrap"
    return PairedProportionTest(
        metric=metric,
        value_new=value_new,
        value_ref=value_ref,
        delta=value_new - value_ref,
        n=n,
        n10=n10,
        n01=n01,
        margin=margin,
        alpha=alpha,
        ci_lower=lower,
        ci_upper=upper,
        method=method,
        non_inferior=lower > -margin,
    )


def _difference(metric: str, threshold: float) -> Statistic:
    target = 1 if metric == "sensitivity" else 0

    def statistic(y: Labels, a: FloatArray, b: FloatArray) -> float:
        members = y == target
        hit_a = predicted_positive(a[members], threshold) == bool(target)
        hit_b = predicted_positive(b[members], threshold) == bool(target)
        return float(hit_a.mean() - hit_b.mean())

    return statistic

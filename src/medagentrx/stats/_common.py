# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the statistics core."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

_STANDARD_NORMAL = NormalDist()


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return _STANDARD_NORMAL.cdf(x)


def norm_ppf(p: float) -> float:
    """Standard normal quantile function for ``0 < p < 1``."""
    return _STANDARD_NORMAL.inv_cdf(p)


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > tiny else tiny
        step = d * c
        h *= step
        if abs(step - 1.0) < 1e-15:
            break
    return h


def regularized_beta(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def t_cdf(x: float, df: float) -> float:
    """Student t cumulative distribution function."""
    if math.isinf(x):
        return 1.0 if x > 0 else 0.0
    tail = 0.5 * regularized_beta(df / 2.0, 0.5, df / (df + x * x))
    return 1.0 - tail if x > 0 else tail


def t_ppf(p: float, df: float) -> float:
    """Student t quantile for ``0 < p < 1``, by bisection on ``t_cdf``."""
    if not 0.0 < p < 1.0:
        raise StatsError(f"p must be in (0, 1), got {p}")
    low, high = -1.0, 1.0
    while t_cdf(low, df) > p:
        low *= 2.0
    while t_cdf(high, df) < p:
        high *= 2.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if t_cdf(mid, df) < p:
            low = mid
        else:
            high = mid
        if high - low < 1e-13:
            break
    return 0.5 * (low + high)


def as_labels(y_true: npt.ArrayLike) -> npt.NDArray[np.int8]:
    """Return ``y_true`` as a 1-D int8 array of zeros and ones with both classes present."""
    y = np.asarray(y_true)
    if y.ndim != 1 or y.size == 0:
        raise StatsError("labels must be a non-empty 1-D array")
    if not np.isin(y, (0, 1)).all():
        raise StatsError("labels must be 0 or 1")
    y8 = y.astype(np.int8)
    n_pos = int(y8.sum())
    if n_pos == 0 or n_pos == y8.size:
        raise StatsError("both outcome classes must be present")
    return y8


def as_scores(scores: npt.ArrayLike, n: int, name: str = "scores") -> FloatArray:
    """Return scores as a finite 1-D float64 array of length ``n``."""
    s = np.asarray(scores, dtype=np.float64)
    if s.ndim != 1 or s.size != n:
        raise StatsError(f"{name} must be a 1-D array of length {n}")
    if not np.isfinite(s).all():
        raise StatsError(f"{name} contain NaN or infinite values")
    return s


def check_alpha(alpha: float) -> None:
    """Refuse an alpha outside (0, 0.5)."""
    if not 0.0 < alpha < 0.5:
        raise StatsError(f"alpha must be in (0, 0.5), got {alpha}")

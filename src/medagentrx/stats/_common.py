# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the statistics core."""

from __future__ import annotations

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

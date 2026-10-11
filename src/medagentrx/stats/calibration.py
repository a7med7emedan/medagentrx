# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Calibration: logistic recalibration, Brier score, ECE and calibration curves.

Logistic recalibration fits logit(P(y = 1)) = a + b * logit(p). The slope is
b from that full fit. Calibration-in-the-large is a from the offset model
logit(P(y = 1)) = a + logit(p), with the slope fixed at 1. Both are fitted by
Newton-Raphson with step halving. Probabilities are clipped to
[1e-10, 1 - 1e-10] before the logit so that 0 and 1 stay finite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError
from medagentrx.stats._common import FloatArray, as_labels, as_scores
from medagentrx.stats.metrics import brier_score

CLIP = 1e-10
MAX_ITERATIONS = 100
TOLERANCE = 1e-10


def logit(p: FloatArray) -> FloatArray:
    """Log-odds of clipped probabilities."""
    clipped = np.clip(p, CLIP, 1.0 - CLIP)
    result: FloatArray = np.log(clipped) - np.log1p(-clipped)
    return result


def _expit(x: FloatArray) -> FloatArray:
    result: FloatArray = 0.5 * (1.0 + np.tanh(0.5 * x))
    return result


def _log_likelihood(y: FloatArray, eta: FloatArray) -> float:
    return float(np.sum(y * eta - np.logaddexp(0.0, eta)))


def fit_logistic(
    y: FloatArray, design: FloatArray, offset: FloatArray | None = None
) -> tuple[FloatArray, FloatArray]:
    """Maximum likelihood logistic regression by Newton-Raphson.

    Args:
        y: Outcomes as floats.
        design: n by k design matrix.
        offset: Optional fixed offset added to the linear predictor.

    Returns:
        Coefficients and their covariance matrix (inverse Fisher information).

    Raises:
        StatsError: If the fit does not converge, for example under separation.
    """
    n, k = design.shape
    off = np.zeros(n) if offset is None else offset
    beta = np.zeros(k)
    current = _log_likelihood(y, design @ beta + off)
    for _ in range(MAX_ITERATIONS):
        eta = design @ beta + off
        mu = _expit(eta)
        weights = mu * (1.0 - mu)
        info = design.T @ (design * weights[:, None])
        gradient = design.T @ (y - mu)
        try:
            step = np.linalg.solve(info, gradient)
        except np.linalg.LinAlgError:
            raise StatsError("calibration fit failed: singular information matrix") from None
        scale = 1.0
        while True:
            candidate = beta + scale * step
            value = _log_likelihood(y, design @ candidate + off)
            if value >= current - 1e-12 or scale < 1e-8:
                break
            scale /= 2.0
        beta, previous, current = candidate, current, value
        if np.max(np.abs(scale * step)) < TOLERANCE or abs(current - previous) < TOLERANCE:
            mu = _expit(design @ beta + off)
            info = design.T @ (design * (mu * (1.0 - mu))[:, None])
            return beta, np.linalg.pinv(info)
    raise StatsError("calibration fit did not converge; the outcomes may be perfectly separated")


@dataclass(frozen=True)
class Calibration:
    """Calibration summary of one model.

    Attributes:
        slope: Recalibration slope b.
        slope_se: Standard error of the slope.
        intercept: Calibration-in-the-large a (slope fixed at 1).
        intercept_se: Standard error of the intercept.
        brier: Brier score.
        ece: Expected calibration error with equal-mass bins.
        n_bins: Number of bins used for the ECE.
    """

    slope: float
    slope_se: float
    intercept: float
    intercept_se: float
    brier: float
    ece: float
    n_bins: int


def calibration(y_true: npt.ArrayLike, scores: npt.ArrayLike, n_bins: int = 10) -> Calibration:
    """Compute slope, intercept, Brier score and ECE for one model."""
    y8 = as_labels(y_true)
    p = as_scores(scores, y8.size)
    y = y8.astype(np.float64)
    lp = logit(p)
    if lp[y8 == 0].max() <= lp[y8 == 1].min() or lp[y8 == 1].max() <= lp[y8 == 0].min():
        raise StatsError(
            "calibration slope cannot be estimated: the outcomes are perfectly separated by risk"
        )
    slope_fit, slope_cov = fit_logistic(y, np.column_stack([np.ones_like(lp), lp]))
    offset_fit, offset_cov = fit_logistic(y, np.ones((y.size, 1)), offset=lp)
    return Calibration(
        slope=float(slope_fit[1]),
        slope_se=math.sqrt(float(slope_cov[1, 1])),
        intercept=float(offset_fit[0]),
        intercept_se=math.sqrt(float(offset_cov[0, 0])),
        brier=brier_score(y8, p),
        ece=expected_calibration_error(y8, p, n_bins),
        n_bins=n_bins,
    )


def _equal_mass_bins(p: FloatArray, n_bins: int) -> list[npt.NDArray[np.intp]]:
    if n_bins < 1:
        raise StatsError(f"n_bins must be at least 1, got {n_bins}")
    order = np.argsort(p, kind="mergesort")
    return [b for b in np.array_split(order, min(n_bins, p.size)) if b.size]


def expected_calibration_error(y: npt.NDArray[np.int8], p: FloatArray, n_bins: int = 10) -> float:
    """ECE: weighted mean absolute gap between observed and predicted risk per bin.

    Bins hold equal numbers of rows after sorting by predicted risk.
    """
    total = 0.0
    for members in _equal_mass_bins(p, n_bins):
        total += members.size * abs(float(y[members].mean()) - float(p[members].mean()))
    return total / p.size


@dataclass(frozen=True)
class CalibrationCurve:
    """Points of a calibration curve: mean predicted risk against observed risk."""

    predicted: FloatArray
    observed: FloatArray
    counts: npt.NDArray[np.int64]


def binned_curve(
    y_true: npt.ArrayLike, scores: npt.ArrayLike, n_bins: int = 10
) -> CalibrationCurve:
    """Calibration curve from equal-mass bins."""
    y = as_labels(y_true)
    p = as_scores(scores, y.size)
    bins = _equal_mass_bins(p, n_bins)
    return CalibrationCurve(
        predicted=np.array([p[b].mean() for b in bins]),
        observed=np.array([y[b].mean() for b in bins], dtype=np.float64),
        counts=np.array([b.size for b in bins], dtype=np.int64),
    )


def isotonic_fit(x: FloatArray, y: FloatArray) -> FloatArray:
    """Non-decreasing least-squares fit of ``y`` on ``x`` (pool adjacent violators).

    Returns fitted values in the original row order. Tied ``x`` share one value.
    """
    order = np.argsort(x, kind="mergesort")
    xs, ys = x[order], y[order]
    _, group_start = np.unique(xs, return_index=True)
    sums = np.add.reduceat(ys, group_start)
    weights = np.diff(np.r_[group_start, xs.size]).astype(np.float64)
    values: list[float] = []
    sizes: list[float] = []
    blocks: list[int] = []
    for total, weight in zip(sums, weights, strict=True):
        values.append(float(total / weight))
        sizes.append(float(weight))
        blocks.append(1)
        while len(values) > 1 and values[-2] > values[-1]:
            merged = sizes[-2] + sizes[-1]
            values[-2] = (values[-2] * sizes[-2] + values[-1] * sizes[-1]) / merged
            sizes[-2] = merged
            blocks[-2] += blocks[-1]
            del values[-1], sizes[-1], blocks[-1]
    per_group = np.repeat(values, blocks)
    fitted_sorted = np.repeat(per_group, weights.astype(np.int64))
    fitted = np.empty_like(fitted_sorted)
    fitted[order] = fitted_sorted
    return fitted

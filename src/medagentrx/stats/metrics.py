# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Point metrics on labels and scores. Inputs are assumed already checked."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from medagentrx.stats._common import FloatArray

Labels = npt.NDArray[np.int8]


def predicted_positive(scores: FloatArray, threshold: float) -> npt.NDArray[np.bool_]:
    """Rows flagged at ``threshold``. A score equal to the threshold is positive."""
    flagged: npt.NDArray[np.bool_] = scores >= threshold
    return flagged


def sensitivity(y: Labels, scores: FloatArray, threshold: float) -> float:
    """True positive rate at ``threshold``."""
    return float(predicted_positive(scores[y == 1], threshold).mean())


def specificity(y: Labels, scores: FloatArray, threshold: float) -> float:
    """True negative rate at ``threshold``."""
    return float((~predicted_positive(scores[y == 0], threshold)).mean())


def average_precision(y: Labels, scores: FloatArray) -> float:
    """Area under the precision-recall curve by the step-wise average precision.

    Tied scores are treated as one threshold.
    """
    order = np.argsort(-scores, kind="mergesort")
    s = scores[order]
    t = y[order].astype(np.float64)
    last_of_group = np.r_[s[1:] != s[:-1], True]
    tp = np.cumsum(t)[last_of_group]
    fp = np.cumsum(1.0 - t)[last_of_group]
    precision = tp / (tp + fp)
    recall = tp / tp[-1]
    gains = np.diff(np.r_[0.0, recall])
    return float(np.sum(gains * precision))


def brier_score(y: Labels, scores: FloatArray) -> float:
    """Mean squared difference between probability and outcome."""
    return float(np.mean((scores - y) ** 2))

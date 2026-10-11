# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Net benefit for decision curve analysis (Vickers and Elkin 2006).

NB(t) = TP / n - FP / n * t / (1 - t), where a row counts as positive when
its predicted risk is at least the threshold t.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError
from medagentrx.stats._common import FloatArray, as_labels, as_scores
from medagentrx.stats.bootstrap import DEFAULT_REPLICATES, BootstrapResult, paired_bootstrap
from medagentrx.stats.metrics import Labels, predicted_positive


def _check_threshold(t: float) -> None:
    if not 0.0 < t < 1.0:
        raise StatsError(f"threshold must be in (0, 1), got {t}")


def net_benefit_raw(y: Labels, scores: FloatArray, t: float) -> float:
    """Net benefit at threshold ``t`` without input checks."""
    flagged = predicted_positive(scores, t)
    n = y.size
    tp = float(np.sum(flagged & (y == 1)))
    fp = float(np.sum(flagged & (y == 0)))
    return tp / n - fp / n * t / (1.0 - t)


def net_benefit(y_true: npt.ArrayLike, scores: npt.ArrayLike, t: float) -> float:
    """Net benefit of a model at threshold ``t``."""
    _check_threshold(t)
    y = as_labels(y_true)
    return net_benefit_raw(y, as_scores(scores, y.size), t)


def treat_all_net_benefit(y_true: npt.ArrayLike, t: float) -> float:
    """Net benefit of treating everyone at threshold ``t``."""
    _check_threshold(t)
    prevalence = float(as_labels(y_true).mean())
    return prevalence - (1.0 - prevalence) * t / (1.0 - t)


@dataclass(frozen=True)
class DecisionCurve:
    """Net benefit across thresholds for one model and for treating everyone."""

    thresholds: FloatArray
    model: FloatArray
    treat_all: FloatArray


def decision_curve(
    y_true: npt.ArrayLike, scores: npt.ArrayLike, thresholds: Sequence[float]
) -> DecisionCurve:
    """Net benefit at each threshold, with the treat-all reference."""
    y = as_labels(y_true)
    s = as_scores(scores, y.size)
    for t in thresholds:
        _check_threshold(t)
    return DecisionCurve(
        thresholds=np.array(thresholds, dtype=np.float64),
        model=np.array([net_benefit_raw(y, s, t) for t in thresholds]),
        treat_all=np.array([treat_all_net_benefit(y, t) for t in thresholds]),
    )


def net_benefit_difference(
    y_true: npt.ArrayLike,
    scores_new: npt.ArrayLike,
    scores_ref: npt.ArrayLike,
    t: float,
    *,
    n_replicates: int = DEFAULT_REPLICATES,
    level: float = 0.95,
    seed: int = 0,
) -> BootstrapResult:
    """Paired bootstrap of NB_new(t) - NB_ref(t)."""
    _check_threshold(t)

    def statistic(y: Labels, a: FloatArray, b: FloatArray) -> float:
        return net_benefit_raw(y, a, t) - net_benefit_raw(y, b, t)

    return paired_bootstrap(
        y_true, scores_new, scores_ref, statistic, n_replicates=n_replicates, level=level, seed=seed
    )

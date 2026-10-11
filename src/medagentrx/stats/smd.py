# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Standardised mean difference between two samples, for population shift.

Numeric features: (mean_1 - mean_2) / sqrt((s_1^2 + s_2^2) / 2), with sample
variances. Categorical features use the multivariate definition of Yang and
Dalton (SAS Global Forum 2012): sqrt((T - C)' S^-1 (T - C)) over the level
proportions without the first level, with S the average of the two
multinomial covariance matrices. Values above 0.1 in absolute size are
usually taken to signal a meaningful difference.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from medagentrx.errors import StatsError

SMD_WARNING = 0.1


def numeric_smd(a: npt.ArrayLike, b: npt.ArrayLike) -> float:
    """SMD of a numeric feature. Returns 0 when both samples are constant and equal."""
    x = np.asarray(a, dtype=np.float64)
    z = np.asarray(b, dtype=np.float64)
    if x.size < 2 or z.size < 2:
        raise StatsError("each sample needs at least two values")
    if not (np.isfinite(x).all() and np.isfinite(z).all()):
        raise StatsError("numeric feature values must be finite")
    pooled = math.sqrt((float(x.var(ddof=1)) + float(z.var(ddof=1))) / 2.0)
    gap = float(x.mean() - z.mean())
    if pooled == 0.0:
        return 0.0 if gap == 0.0 else math.copysign(math.inf, gap)
    return gap / pooled


def categorical_smd(a: Sequence[str], b: Sequence[str]) -> float:
    """Multivariate SMD of a categorical feature. Always zero or positive."""
    if not a or not b:
        raise StatsError("each sample needs at least one value")
    levels = sorted(set(a) | set(b))
    if len(levels) < 2:
        return 0.0
    count_a, count_b = Counter(a), Counter(b)
    p1 = np.array([count_a[level] for level in levels], dtype=np.float64) / len(a)
    p2 = np.array([count_b[level] for level in levels], dtype=np.float64) / len(b)
    t, c = p1[1:], p2[1:]
    s = (np.diag(t * (1 - t) + c * (1 - c)) - np.outer(t, t) - np.outer(c, c)) / 2.0
    np.fill_diagonal(s, (t * (1 - t) + c * (1 - c)) / 2.0)
    d = t - c
    return float(math.sqrt(max(float(d @ np.linalg.pinv(s) @ d), 0.0)))

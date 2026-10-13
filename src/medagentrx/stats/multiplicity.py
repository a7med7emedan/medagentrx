# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Multiplicity across subgroups: intersection-union, Holm (1979) and Bonferroni.

The subgroup criterion passes only when every subgroup is non-inferior. That
is an intersection-union test (Berger 1982): each hypothesis may be tested at
the full level, and the family-wise error of a wrong pass stays at alpha.
Holm and Bonferroni are valid but stricter, and remain available.

``holm`` returns, for each hypothesis, the one-sided level it was tested at
in the step-down sequence and whether it was rejected. Intervals reported at
those levels are the ones the subgroup criterion uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from medagentrx.errors import StatsError


@dataclass(frozen=True)
class Adjustment:
    """Outcome of a multiplicity correction.

    Attributes:
        adjusted_p: Adjusted p-values, in input order.
        levels: Level each hypothesis was tested at, in input order.
        rejected: Whether each hypothesis was rejected, in input order.
    """

    adjusted_p: tuple[float, ...]
    levels: tuple[float, ...]
    rejected: tuple[bool, ...]


def _check(p_values: Sequence[float], alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise StatsError(f"alpha must be in (0, 1), got {alpha}")
    for p in p_values:
        if not 0.0 <= p <= 1.0:
            raise StatsError(f"p-values must be in [0, 1], got {p}")


def intersection_union(p_values: Sequence[float], alpha: float) -> Adjustment:
    """Intersection-union test: every hypothesis is tested at alpha, with no correction."""
    _check(p_values, alpha)
    return Adjustment(
        adjusted_p=tuple(p_values),
        levels=(alpha,) * len(p_values),
        rejected=tuple(p <= alpha for p in p_values),
    )


def bonferroni(p_values: Sequence[float], alpha: float) -> Adjustment:
    """Bonferroni: every hypothesis is tested at alpha / m."""
    _check(p_values, alpha)
    m = len(p_values)
    if m == 0:
        return Adjustment((), (), ())
    level = alpha / m
    return Adjustment(
        adjusted_p=tuple(min(1.0, p * m) for p in p_values),
        levels=(level,) * m,
        rejected=tuple(p <= level for p in p_values),
    )


def holm(p_values: Sequence[float], alpha: float) -> Adjustment:
    """Holm step-down: sort p-values; test the i-th smallest at alpha / (m - i).

    Testing stops at the first failure. Hypotheses not reached are reported at
    the level of that first failure.
    """
    _check(p_values, alpha)
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    levels = [0.0] * m
    rejected = [False] * m
    running = 0.0
    stopped_at: float | None = None
    for step, index in enumerate(order):
        running = max(running, min(1.0, (m - step) * p_values[index]))
        adjusted[index] = running
        level = alpha / (m - step)
        if stopped_at is None and p_values[index] <= level:
            levels[index] = level
            rejected[index] = True
        else:
            stopped_at = level if stopped_at is None else stopped_at
            levels[index] = stopped_at
    return Adjustment(tuple(adjusted), tuple(levels), tuple(rejected))

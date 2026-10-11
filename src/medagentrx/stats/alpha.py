# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Spending the plan's alpha across updates.

Bonferroni gives update k the level alpha_total / max_updates. It controls
the family-wise error rate over the whole plan.

Alpha-investing (Foster and Stine, JRSS-B 2008) starts with wealth
W0 = alpha_total * (1 - alpha_total). Update k may test at
alpha_k = (W / (1 + W)) / R, where R is the number of updates still allowed.
A rejection, here an accepted non-inferiority test, earns the payout
omega = alpha_total. A non-rejection costs alpha_k / (1 - alpha_k). This
controls the marginal false discovery rate, not the family-wise error rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from medagentrx.errors import StatsError

Method = Literal["bonferroni", "alpha_investing"]


@dataclass(frozen=True)
class AlphaState:
    """Alpha accounting after some updates.

    Attributes:
        method: Spending rule.
        alpha_total: Total alpha of the plan.
        max_updates: Updates allowed by the plan.
        updates_tested: Updates evaluated so far.
        spent: Sum of the levels used so far.
        wealth: Remaining wealth (alpha-investing only; for Bonferroni the unspent alpha).
    """

    method: Method
    alpha_total: float
    max_updates: int
    updates_tested: int
    spent: float
    wealth: float

    @property
    def exhausted(self) -> bool:
        """True when no further update can be tested."""
        return self.updates_tested >= self.max_updates or self.wealth <= 0.0


def initial_state(method: Method, alpha_total: float, max_updates: int) -> AlphaState:
    """State before the first update."""
    if not 0.0 < alpha_total < 1.0:
        raise StatsError(f"alpha_total must be in (0, 1), got {alpha_total}")
    if max_updates < 1:
        raise StatsError(f"max_updates must be at least 1, got {max_updates}")
    wealth = alpha_total if method == "bonferroni" else alpha_total * (1.0 - alpha_total)
    return AlphaState(method, alpha_total, max_updates, 0, 0.0, wealth)


def next_alpha(state: AlphaState) -> float:
    """Level available to the next update.

    Raises:
        StatsError: If the budget is exhausted.
    """
    if state.exhausted:
        raise StatsError("the alpha budget of this plan is exhausted")
    if state.method == "bonferroni":
        return state.alpha_total / state.max_updates
    remaining = state.max_updates - state.updates_tested
    return (state.wealth / (1.0 + state.wealth)) / remaining


def record(state: AlphaState, alpha_used: float, *, rejected: bool) -> AlphaState:
    """Return the state after one update tested at ``alpha_used``."""
    if state.method == "bonferroni":
        wealth = state.wealth - alpha_used
    elif rejected:
        wealth = state.wealth + state.alpha_total
    else:
        wealth = state.wealth - alpha_used / (1.0 - alpha_used)
    return AlphaState(
        method=state.method,
        alpha_total=state.alpha_total,
        max_updates=state.max_updates,
        updates_tested=state.updates_tested + 1,
        spent=state.spent + alpha_used,
        wealth=max(wealth, 0.0),
    )

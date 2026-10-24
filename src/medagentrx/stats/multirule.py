# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Multirule quality control on the run bias of deployment QC.

Each QC run gives one number, its bias: the mean of live minus expected score
over the control records. It is standardised as ``z = (bias - mean) / sd`` and
judged with the multirule scheme of Westgard et al. (1981). There is one
control material, so the rules look across successive runs:

- ``1_2s``: the latest run is more than 2 SD from the mean. A warning only.
- ``1_3s``: the latest run is more than 3 SD from the mean.
- ``2_2s``: the latest two runs are both more than 2 SD from the mean, on the
  same side.
- ``R_4s``: of the latest two runs, one is more than 2 SD above the mean and
  the other more than 2 SD below.
- ``10_x``: the latest ten runs all lie on the same side of the mean.

"More than" is strict: a run exactly 2 SD from the mean does not fire 1_2s,
and a run exactly on the mean breaks a 10_x sequence.

Reference: Westgard J. O., Barry P. L., Hunt M. R., Groth T. A multi-rule
Shewhart chart for quality control in clinical chemistry. Clinical Chemistry
1981;27(3):493 to 501.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from medagentrx.errors import StatsError

WARNING_RULES = ("1_2s",)
REJECTION_RULES = ("1_3s", "2_2s", "R_4s", "10_x")
RULE_TEXT = {
    "1_2s": "the latest run is more than 2 SD from the mean",
    "1_3s": "the latest run is more than 3 SD from the mean",
    "2_2s": "the latest two runs are more than 2 SD from the mean on the same side",
    "R_4s": "the latest two runs lie more than 2 SD on opposite sides of the mean",
    "10_x": "the latest ten runs lie on the same side of the mean",
}


@dataclass(frozen=True)
class Baseline:
    """Target mean and SD of the run bias.

    Attributes:
        mean: Target bias.
        sd: Standard deviation of the bias, after any floor.
        estimated_sd: SD estimated from the baseline runs, or None if given.
        floored: True when the floor replaced a smaller estimate.
        runs: Baseline runs used, or 0 when the SD was given.
    """

    mean: float
    sd: float
    estimated_sd: float | None
    floored: bool
    runs: int


@dataclass(frozen=True)
class RuleOutcome:
    """Rules that fired on the latest run.

    Attributes:
        z: Standardised bias of each run, oldest first; the last is the latest run.
        rejections: Rejection rules that fired.
        warnings: Warning rules that fired.
    """

    z: tuple[float, ...]
    rejections: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def in_control(self) -> bool:
        """True when no rejection rule fired."""
        return not self.rejections


def given_baseline(sd: float) -> Baseline:
    """Baseline when the plan gives the SD: the target bias is zero."""
    if not (sd > 0.0 and math.isfinite(sd)):
        raise StatsError(f"sd must be positive and finite, got {sd}")
    return Baseline(mean=0.0, sd=sd, estimated_sd=None, floored=False, runs=0)


def estimate_baseline(biases: Sequence[float], *, floor: float) -> Baseline:
    """Mean and sample SD of the baseline runs' bias, with the SD no smaller than ``floor``.

    A deterministic stack reproduces its scores exactly, so its SD is zero. The
    floor keeps rounding from counting as a shift.

    Raises:
        StatsError: If fewer than two runs are given or ``floor`` is not positive.
    """
    if len(biases) < 2:
        raise StatsError("at least two baseline runs are needed to estimate an SD")
    if not floor > 0.0:
        raise StatsError(f"floor must be positive, got {floor}")
    n = len(biases)
    mean = math.fsum(biases) / n
    sd = math.sqrt(math.fsum((b - mean) ** 2 for b in biases) / (n - 1))
    return Baseline(mean=mean, sd=max(sd, floor), estimated_sd=sd, floored=sd < floor, runs=n)


def standardise(biases: Sequence[float], baseline: Baseline) -> tuple[float, ...]:
    """Standardised bias of each run."""
    return tuple((b - baseline.mean) / baseline.sd for b in biases)


def evaluate_rules(z: Sequence[float], rules: Sequence[str]) -> RuleOutcome:
    """Apply ``rules`` to the latest run, given every run's standardised bias.

    Raises:
        StatsError: If ``z`` is empty or a rule is unknown.
    """
    if not z:
        raise StatsError("at least one run is needed")
    unknown = [r for r in rules if r not in RULE_TEXT]
    if unknown:
        raise StatsError(f"unknown QC rule(s): {', '.join(unknown)}")
    latest = z[-1]
    fired: list[str] = []
    if "1_2s" in rules and abs(latest) > 2.0:
        fired.append("1_2s")
    if "1_3s" in rules and abs(latest) > 3.0:
        fired.append("1_3s")
    if len(z) >= 2:
        previous = z[-2]
        if "2_2s" in rules and (
            (latest > 2.0 and previous > 2.0) or (latest < -2.0 and previous < -2.0)
        ):
            fired.append("2_2s")
        if "R_4s" in rules and (
            (latest > 2.0 and previous < -2.0) or (latest < -2.0 and previous > 2.0)
        ):
            fired.append("R_4s")
    if "10_x" in rules and len(z) >= 10:
        window = z[-10:]
        if all(v > 0.0 for v in window) or all(v < 0.0 for v in window):
            fired.append("10_x")
    return RuleOutcome(
        z=tuple(z),
        rejections=tuple(r for r in fired if r in REJECTION_RULES),
        warnings=tuple(r for r in fired if r in WARNING_RULES),
    )

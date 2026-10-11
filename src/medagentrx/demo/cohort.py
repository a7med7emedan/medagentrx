# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Synthetic sepsis cohort. No real patient data is used or implied.

The locked test set has about 20,000 adult inpatients with a sepsis
prevalence near 12 percent. Each row has a true risk logit; outcomes are
drawn from it. Model versions are built from that logit with added noise,
so their ranking quality is known, and each is recalibrated on the test set
so it starts out well calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from medagentrx.stats.calibration import fit_logistic
from medagentrx.stats.delong import auc_fast

FloatArray = npt.NDArray[np.float64]
Labels = npt.NDArray[np.int8]

SITES = ("A", "B", "C")
AGE_BANDS = ("18-44", "45-64", "65+")
DEFAULT_SEED = 20260301


@dataclass(frozen=True)
class Cohort:
    """The synthetic locked test set and training manifest.

    Attributes:
        truth: True risk logit per test row.
        y: Outcome per test row.
        noise: One standard normal draw per test row, shared by all versions.
        test: Test columns other than scores: row_id, patient_id, sex, age, age_band, site.
        train: Training manifest columns.
    """

    truth: FloatArray
    y: Labels
    noise: FloatArray
    test: dict[str, list[object]]
    train: dict[str, list[object]]

    @property
    def n(self) -> int:
        """Rows in the test set."""
        return int(self.y.size)


def _age_band(age: int) -> str:
    if age < 45:
        return AGE_BANDS[0]
    if age < 65:
        return AGE_BANDS[1]
    return AGE_BANDS[2]


def make_cohort(n_test: int = 20_000, n_train: int = 30_000, seed: int = DEFAULT_SEED) -> Cohort:
    """Draw the cohort. The same seed always gives the same cohort."""
    rng = np.random.default_rng(seed)
    age = rng.integers(18, 96, size=n_test)
    sex = rng.choice(["F", "M"], size=n_test)
    site = rng.choice(SITES, size=n_test, p=[0.4, 0.35, 0.25])
    lactate = np.round(np.clip(rng.lognormal(0.4, 0.45, n_test), 0.3, 15.0), 1)
    latent = rng.normal(size=n_test)
    truth = -2.5 + 0.012 * (age - 60) + 0.25 * (lactate - 1.6) + 1.35 * latent
    y = (rng.random(n_test) < 1.0 / (1.0 + np.exp(-truth))).astype(np.int8)
    noise = rng.normal(size=n_test)
    test: dict[str, list[object]] = {
        "row_id": [f"T{i:06d}" for i in range(n_test)],
        "patient_id": [f"P{i:06d}" for i in range(n_test)],
        "sex": sex.tolist(),
        "age": age.tolist(),
        "age_band": [_age_band(int(a)) for a in age],
        "site": site.tolist(),
        "lactate": lactate.tolist(),
    }
    train_age = rng.integers(18, 96, size=n_train)
    days = rng.integers(0, 1277, size=n_train)
    start = np.datetime64("2023-01-01")
    train: dict[str, list[object]] = {
        "row_id": [f"R{i:06d}" for i in range(n_train)],
        "patient_id": [f"Q{i:06d}" for i in range(n_train)],
        "sex": rng.choice(["F", "M"], size=n_train).tolist(),
        "age": train_age.tolist(),
        "site": rng.choice(SITES, size=n_train, p=[0.4, 0.35, 0.25]).tolist(),
        "admission_date": [str(start + np.timedelta64(int(d), "D")) for d in days],
        "lactate": np.round(np.clip(rng.lognormal(0.4, 0.45, n_train), 0.3, 15.0), 1).tolist(),
    }
    return Cohort(truth=truth, y=y, noise=noise, test=test, train=train)


def recalibrated(y: Labels, logit: FloatArray) -> FloatArray:
    """Probabilities after a logistic recalibration of ``logit`` on ``y``."""
    design = np.column_stack([np.ones_like(logit), logit])
    beta, _ = fit_logistic(y.astype(np.float64), design)
    result: FloatArray = 1.0 / (1.0 + np.exp(-(design @ beta)))
    return result


def noisy_logit(
    cohort: Cohort, sigma: float, members: npt.NDArray[np.bool_] | None = None
) -> FloatArray:
    """True logit plus ``sigma`` times the shared noise draw, optionally only for ``members``."""
    extra = sigma * cohort.noise
    if members is not None:
        extra = np.where(members, extra, 0.0)
    result: FloatArray = cohort.truth + extra
    return result


def sigma_for_auc(
    cohort: Cohort,
    target: float,
    *,
    base: FloatArray | None = None,
    members: npt.NDArray[np.bool_] | None = None,
) -> float:
    """Noise level whose version reaches AUROC ``target`` on ``members`` (all rows by default).

    ``base`` is a logit to which the noise is added instead of the true logit.
    """
    mask = np.ones(cohort.n, dtype=bool) if members is None else members
    start = cohort.truth if base is None else base
    y = cohort.y[mask]

    def auc(sigma: float) -> float:
        return auc_fast(y, (start + sigma * cohort.noise)[mask])

    low, high = 0.0, 8.0
    if auc(low) < target:
        raise ValueError(f"target AUROC {target} is above the noiseless value {auc(low):.4f}")
    for _ in range(60):
        mid = 0.5 * (low + high)
        if auc(mid) > target:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)

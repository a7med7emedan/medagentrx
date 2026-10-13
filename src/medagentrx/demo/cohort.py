# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Synthetic sepsis cohort. No real patient data is used or implied.

The locked test set has about 20,000 adult inpatients with a sepsis
prevalence near 12 percent. Each row has a true risk logit; outcomes are
drawn from it. Model versions are built from that logit with added noise,
so their ranking quality is known.

A separate development sample is drawn from the same process. Each version
is recalibrated on it, never on the locked test set, as a real team would
recalibrate on its own validation data. The test set then shows the small
calibration error a real update carries.
"""

from __future__ import annotations

from collections.abc import Callable
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
        development: Rows drawn the same way as the test set, for recalibration
            only. None inside a development sample.
    """

    truth: FloatArray
    y: Labels
    noise: FloatArray
    test: dict[str, list[object]]
    train: dict[str, list[object]]
    development: Cohort | None = None

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


def _draw_patients(
    rng: np.random.Generator, n: int, row_prefix: str, patient_prefix: str
) -> tuple[FloatArray, Labels, FloatArray, dict[str, list[object]]]:
    age = rng.integers(18, 96, size=n)
    sex = rng.choice(["F", "M"], size=n)
    site = rng.choice(SITES, size=n, p=[0.4, 0.35, 0.25])
    lactate = np.round(np.clip(rng.lognormal(0.4, 0.45, n), 0.3, 15.0), 1)
    latent = rng.normal(size=n)
    truth = -2.5 + 0.012 * (age - 60) + 0.25 * (lactate - 1.6) + 1.35 * latent
    y = (rng.random(n) < 1.0 / (1.0 + np.exp(-truth))).astype(np.int8)
    noise = rng.normal(size=n)
    columns: dict[str, list[object]] = {
        "row_id": [f"{row_prefix}{i:06d}" for i in range(n)],
        "patient_id": [f"{patient_prefix}{i:06d}" for i in range(n)],
        "sex": sex.tolist(),
        "age": age.tolist(),
        "age_band": [_age_band(int(a)) for a in age],
        "site": site.tolist(),
        "lactate": lactate.tolist(),
    }
    return truth, y, noise, columns


def make_cohort(
    n_test: int = 20_000,
    n_train: int = 30_000,
    seed: int = DEFAULT_SEED,
    n_development: int | None = None,
) -> Cohort:
    """Draw the cohort. The same seed always gives the same cohort.

    ``n_development`` defaults to ``n_test``. The development sample has its
    own random stream, so its size never changes the test set.
    """
    rng = np.random.default_rng(seed)
    truth, y, noise, test = _draw_patients(rng, n_test, "T", "P")
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
    dev_rng = np.random.default_rng([seed, 1])
    dev_truth, dev_y, dev_noise, dev_columns = _draw_patients(
        dev_rng, n_test if n_development is None else n_development, "D", "V"
    )
    development = Cohort(dev_truth, dev_y, dev_noise, dev_columns, train={})
    return Cohort(truth, y, noise, test, train, development)


Recipe = Callable[[Cohort], FloatArray]
"""A model version: how its risk logit follows from a cohort's rows."""


def logistic_recalibration(y: Labels, logit: FloatArray) -> tuple[float, float]:
    """Intercept and slope of a logistic recalibration of ``logit`` on ``y``."""
    design = np.column_stack([np.ones_like(logit), logit])
    beta, _ = fit_logistic(y.astype(np.float64), design)
    return float(beta[0]), float(beta[1])


def calibrated_probabilities(cohort: Cohort, recipe: Recipe) -> FloatArray:
    """The version's test-set probabilities, recalibrated on the development sample."""
    if cohort.development is None:
        raise ValueError("the cohort has no development sample to recalibrate on")
    dev = cohort.development
    intercept, slope = logistic_recalibration(dev.y, recipe(dev))
    result: FloatArray = 1.0 / (1.0 + np.exp(-(intercept + slope * recipe(cohort))))
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


def noisy(
    sigma: float,
    harmed: Callable[[Cohort], npt.NDArray[np.bool_]] | None = None,
    harmed_sigma: float | None = None,
) -> Recipe:
    """A version whose logit is the truth plus ``sigma`` times the shared noise draw.

    Rows selected by ``harmed`` get ``harmed_sigma`` instead.
    """

    def recipe(cohort: Cohort) -> FloatArray:
        scale = np.full(cohort.n, sigma)
        if harmed is not None and harmed_sigma is not None:
            scale = np.where(harmed(cohort), harmed_sigma, scale)
        result: FloatArray = cohort.truth + scale * cohort.noise
        return result

    return recipe

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Write the fixed datasets used for the pROC cross-check.

Run from the repository root:
    uv run python tests/reference/pROC/make_datasets.py
then:
    Rscript tests/reference/pROC/delong_reference.R
"""

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def _write(name: str, y: np.ndarray, s1: np.ndarray, s2: np.ndarray) -> None:
    lines = ["y,s1,s2"] + [
        f"{int(a)},{float(b)!r},{float(c)!r}" for a, b, c in zip(y, s1, s2, strict=True)
    ]
    (HERE / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rng = np.random.default_rng(20260101)
    n = 60
    y = (rng.random(n) < 0.4).astype(int)
    s1 = rng.normal(y * 1.0)
    _write("small", y, s1, s1 + rng.normal(0, 0.8, n))

    n = 2000
    y = (rng.random(n) < 0.12).astype(int)
    latent = rng.normal(y * 1.2)
    _write("prevalence12", y, latent, 0.7 * latent + rng.normal(0, 0.6, n))

    n = 800
    y = (rng.random(n) < 0.3).astype(int)
    s1 = np.round(1 / (1 + np.exp(-rng.normal(y * 1.0 - 0.5))), 1)
    s2 = np.round(1 / (1 + np.exp(-rng.normal(y * 0.8 - 0.5))), 1)
    _write("ties", y, s1.astype(float), s2.astype(float))

    n = 500
    y = (rng.random(n) < 0.5).astype(int)
    s1 = rng.normal(y * 2.0)
    _write("strong", y, s1, -rng.normal(-(y * 0.3)))


if __name__ == "__main__":
    main()

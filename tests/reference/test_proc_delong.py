# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""DeLong agreement with R pROC on fixed datasets.

Tolerances from the release gate: 1e-8 on AUC, 1e-6 on SE and z.
CI also reruns the R script and fails if expected.json changes.
"""

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from medagentrx.stats.delong import delong, paired_auc_test

HERE = Path(__file__).resolve().parent / "pROC"
EXPECTED = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))["datasets"]


def _load(name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with (HERE / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    y = np.array([int(r["y"]) for r in rows])
    s1 = np.array([float(r["s1"]) for r in rows])
    s2 = np.array([float(r["s2"]) for r in rows])
    return y, s1, s2


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_delong_matches_proc(name: str) -> None:
    expected = EXPECTED[name]
    y, s1, s2 = _load(name)
    result = delong(y, s1, s2)
    assert abs(result.auc[0] - expected["auc1"]) < 1e-8
    assert abs(result.auc[1] - expected["auc2"]) < 1e-8
    assert abs(math.sqrt(result.cov[0, 0]) - expected["se1"]) < 1e-6
    assert abs(math.sqrt(result.cov[1, 1]) - expected["se2"]) < 1e-6
    assert abs(result.cov[0, 1] - expected["cov12"]) < 1e-6
    test = paired_auc_test(y, s1, s2, margin=0.0, alpha=0.025)
    assert abs(test.z - expected["z"]) < 1e-6

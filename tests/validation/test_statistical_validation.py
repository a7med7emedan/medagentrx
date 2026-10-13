# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Statistical validation across the simulation grid.

The full grid is slow and runs nightly and before release:
    uv run pytest -m slow
A quick check of the simulation itself runs with every test run.
"""

import importlib
import math
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from medagentrx.stats.delong import auc_fast
from tests.conftest import REPO_ROOT


def _load() -> ModuleType:
    """Import scripts/validation.py by name, so worker processes can import it too."""
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("validation")


validation = _load()


def test_simulation_has_the_intended_auroc() -> None:
    rng = np.random.default_rng(0)
    y, new, ref = validation._draw(rng, 200_000, 0.2, 0.78)
    assert auc_fast(y, new) == pytest.approx(0.78, abs=0.003)
    assert auc_fast(y, ref) == pytest.approx(validation.REFERENCE_AUC, abs=0.003)
    assert y.mean() == pytest.approx(0.2, abs=1e-6)
    assert np.corrcoef(new[y == 0], ref[y == 0])[0, 1] == pytest.approx(
        validation.CORRELATION, abs=0.01
    )


def test_shift_inverts_the_binormal_auroc() -> None:
    from statistics import NormalDist

    assert NormalDist().cdf(validation._shift(0.8) / math.sqrt(2)) == pytest.approx(0.8)


def test_check_flags_cells_outside_the_bands() -> None:
    cell = validation.Cell(0.1, 500, 0.07, 0.5, 0.90, 10, 10)
    problems = validation.check([cell])
    assert len(problems) == 2


@pytest.mark.slow
def test_type_i_error_and_coverage_across_the_grid(tmp_path: Path) -> None:
    cells = validation.run_grid()
    assert len(cells) == len(validation.PREVALENCES) * len(validation.SIZES)
    assert validation.check(cells) == []
    for cell in cells:
        assert cell.power > cell.type_i_error
    svg = validation.figure(cells)
    assert svg.startswith("<svg")

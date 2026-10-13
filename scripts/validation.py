# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Statistical validation of the non-inferiority test and the bootstrap intervals.

Simulation grid: prevalence 5, 12 and 30 percent; test sets of 500, 2,000
and 20,000 rows. Scores of the two models are binormal and correlated
within each row (correlation 0.8).

- Type I error: the new model is worse by exactly the margin
  (true AUROC difference = -0.02). The one-sided DeLong non-inferiority test
  at alpha 0.05, with its small-sample t reference, should reject about
  5 percent of the time.
- Power: the two models are equally good; share of rejections.
- Coverage: the paired stratified bootstrap 95 percent percentile interval,
  with the default 2,000 replicates,
  of the net benefit difference at threshold 0.2 should contain the true
  difference about 95 percent of the time.

Replicates per cell (20,000 for rejection rates, 10,000 for coverage) keep
the Monte Carlo standard error near 0.0016 and 0.0023, small next to the
acceptance bands. With 25 positives (5 percent of 500 rows) the percentile
interval covers about 93.3 percent, inside its band but near the edge.

Run from the repository root:
    uv run python scripts/validation.py --out docs/assets
It writes validation.json and validation.svg (the README figure).
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np

from medagentrx.stats.bootstrap import paired_bootstrap
from medagentrx.stats.delong import delong, paired_test_from
from medagentrx.stats.net_benefit import net_benefit_raw

PREVALENCES = (0.05, 0.12, 0.30)
SIZES = (500, 2_000, 20_000)
ALPHA = 0.05
MARGIN = 0.02
REFERENCE_AUC = 0.80
CORRELATION = 0.8
THRESHOLD = 0.2
TYPE_I_REPLICATES = 20_000
COVERAGE_REPLICATES = 10_000
BLOCKS = 10
"""Each cell is split into this many seed blocks that run in parallel."""
BOOTSTRAP_REPLICATES = 2_000
TYPE_I_BOUNDS = (0.04, 0.06)
COVERAGE_BOUNDS = (0.93, 0.97)


def _shift(auc: float) -> float:
    """Mean shift of positives giving ``auc`` for unit-variance binormal scores."""
    return math.sqrt(2.0) * NormalDist().inv_cdf(auc)


def _draw(
    rng: np.random.Generator, n: int, prevalence: float, auc_new: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_pos = max(2, round(n * prevalence))
    y = np.r_[np.ones(n_pos, dtype=np.int8), np.zeros(n - n_pos, dtype=np.int8)]
    cov = np.array([[1.0, CORRELATION], [CORRELATION, 1.0]])
    scores = rng.multivariate_normal([0.0, 0.0], cov, size=n)
    scores[:n_pos, 0] += _shift(auc_new)
    scores[:n_pos, 1] += _shift(REFERENCE_AUC)
    return y, scores[:, 0], scores[:, 1]


def _risk(score: np.ndarray, prevalence: float) -> np.ndarray:
    """A fixed monotone map from score to risk, the same for both models."""
    base = math.log(prevalence / (1.0 - prevalence))
    result: np.ndarray = 1.0 / (1.0 + np.exp(-(base + 1.2 * score)))
    return result


def _rejection_rate(prevalence: float, n: int, auc_new: float, seed: int, replicates: int) -> float:
    rng = np.random.default_rng(seed)
    rejected = 0
    for _ in range(replicates):
        y, new, ref = _draw(rng, n, prevalence, auc_new)
        test = paired_test_from(delong(y, new, ref), 0, 1, margin=MARGIN, alpha=ALPHA)
        rejected += int(test.non_inferior)
    return rejected / replicates


def _true_nb_difference(prevalence: float, seed: int) -> float:
    rng = np.random.default_rng(seed)
    y, new, ref = _draw(rng, 2_000_000, prevalence, REFERENCE_AUC - MARGIN)
    return net_benefit_raw(y, _risk(new, prevalence), THRESHOLD) - net_benefit_raw(
        y, _risk(ref, prevalence), THRESHOLD
    )


def _coverage(prevalence: float, n: int, truth: float, seed: int, replicates: int) -> float:
    rng = np.random.default_rng(seed)

    def difference(yy: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
        return net_benefit_raw(yy, a, THRESHOLD) - net_benefit_raw(yy, b, THRESHOLD)

    covered = 0
    for i in range(replicates):
        y, new, ref = _draw(rng, n, prevalence, REFERENCE_AUC - MARGIN)
        result = paired_bootstrap(
            y,
            _risk(new, prevalence),
            _risk(ref, prevalence),
            difference,
            n_replicates=BOOTSTRAP_REPLICATES,
            seed=seed + i,
            jackknife_groups=20,
        )
        low, high = result.percentile
        covered += int(low <= truth <= high)
    return covered / replicates


@dataclass(frozen=True)
class Cell:
    """Results for one prevalence and test-set size."""

    prevalence: float
    n: int
    type_i_error: float
    power: float
    coverage: float
    type_i_replicates: int
    coverage_replicates: int


def _task(args: tuple[str, float, int, int, float]) -> tuple[str, float, int, float]:
    kind, prevalence, n, seed, truth = args
    if kind == "type_i":
        value = _rejection_rate(
            prevalence, n, REFERENCE_AUC - MARGIN, seed, TYPE_I_REPLICATES // BLOCKS
        )
    elif kind == "power":
        value = _rejection_rate(prevalence, n, REFERENCE_AUC, seed, TYPE_I_REPLICATES // BLOCKS)
    else:
        value = _coverage(prevalence, n, truth, seed, COVERAGE_REPLICATES // BLOCKS)
    return kind, prevalence, n, value


def run_grid(workers: int | None = None) -> list[Cell]:
    """Simulate every cell in parallel seed blocks; results depend only on the seeds."""
    with ProcessPoolExecutor(max_workers=workers) as pool:
        truths = dict(
            zip(
                PREVALENCES,
                pool.map(_true_nb_difference, PREVALENCES, [7 + i for i in range(3)]),
                strict=True,
            )
        )
        tasks = [
            (kind, prevalence, n, 100_000 * k + 1_000 * i + 10 * j + b, truths[prevalence])
            for k, kind in enumerate(("type_i", "power", "coverage"))
            for i, prevalence in enumerate(PREVALENCES)
            for j, n in enumerate(SIZES)
            for b in range(BLOCKS)
        ]
        results = list(pool.map(_task, tasks))
    cells = []
    for prevalence in PREVALENCES:
        for n in SIZES:
            means = {
                kind: float(
                    np.mean([v for k, p, m, v in results if (k, p, m) == (kind, prevalence, n)])
                )
                for kind in ("type_i", "power", "coverage")
            }
            cells.append(
                Cell(
                    prevalence,
                    n,
                    means["type_i"],
                    means["power"],
                    means["coverage"],
                    TYPE_I_REPLICATES,
                    COVERAGE_REPLICATES,
                )
            )
    return cells


def figure(cells: list[Cell]) -> str:
    """Three panels: type I error, power and coverage across the grid."""
    import io

    import matplotlib as mpl
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    from medagentrx.report.figures import AMBER, GREY, SLATE, TEAL, clean_svg

    styles = {0.05: (TEAL, "o", "-"), 0.12: (SLATE, "s", "--"), 0.30: (AMBER, "^", ":")}
    with mpl.rc_context(
        {
            "svg.fonttype": "path",
            "svg.hashsalt": "medagentrx",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    ):
        fig = Figure(figsize=(9.6, 3.2), layout="constrained")
        FigureCanvasSVG(fig)
        panels = fig.subplots(1, 3)
        specs = [
            ("type_i_error", "Type I error (true difference = -margin)", TYPE_I_BOUNDS, ALPHA),
            ("power", "Power (equal models)", None, None),
            ("coverage", "Bootstrap 95% CI coverage", COVERAGE_BOUNDS, 0.95),
        ]
        for ax, (key, title, bounds, nominal) in zip(panels, specs, strict=True):
            if bounds:
                ax.axhspan(*bounds, color=GREY, alpha=0.15, label="Acceptance band")
            if nominal:
                ax.axhline(nominal, color=GREY, linewidth=0.8)
            for prevalence in PREVALENCES:
                row = [c for c in cells if c.prevalence == prevalence]
                colour, marker, line = styles[prevalence]
                ax.plot(
                    [c.n for c in row],
                    [getattr(c, key) for c in row],
                    marker=marker,
                    linestyle=line,
                    color=colour,
                    label=f"Prevalence {prevalence:.0%}",
                )
            ax.set_xscale("log")
            ax.set_xticks(list(SIZES), [f"{n:,}" for n in SIZES])
            ax.minorticks_off()
            ax.set_xlabel("Test-set rows")
            ax.set_title(title, fontsize=9)
        panels[1].set_ylim(0, 1.02)
        panels[0].legend(fontsize=7, loc="upper right")
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", metadata={"Date": None, "Creator": None})
    return clean_svg(buffer.getvalue())


def check(cells: list[Cell]) -> list[str]:
    """Cells outside the acceptance bands."""
    problems = []
    for c in cells:
        if not TYPE_I_BOUNDS[0] <= c.type_i_error <= TYPE_I_BOUNDS[1]:
            problems.append(
                f"type I error {c.type_i_error:.4f} at prevalence {c.prevalence}, n {c.n}"
            )
        if not COVERAGE_BOUNDS[0] <= c.coverage <= COVERAGE_BOUNDS[1]:
            problems.append(f"coverage {c.coverage:.4f} at prevalence {c.prevalence}, n {c.n}")
    return problems


def main() -> None:
    """Run the grid and write the results and the figure."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument(
        "--figure-only",
        action="store_true",
        help="Redraw validation.svg from an existing validation.json without simulating.",
    )
    args = parser.parse_args()
    if args.figure_only:
        saved = json.loads((args.out / "validation.json").read_text(encoding="utf-8"))
        cells = [Cell(**c) for c in saved["cells"]]
        (args.out / "validation.svg").write_text(figure(cells) + "\n", encoding="utf-8")
        return
    cells = run_grid(args.workers)
    args.out.mkdir(parents=True, exist_ok=True)
    results = {
        "settings": {
            "alpha": ALPHA,
            "margin": MARGIN,
            "reference_auc": REFERENCE_AUC,
            "correlation": CORRELATION,
            "threshold": THRESHOLD,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "type_i_bounds": TYPE_I_BOUNDS,
            "coverage_bounds": COVERAGE_BOUNDS,
        },
        "cells": [asdict(c) for c in cells],
        "problems": check(cells),
    }
    (args.out / "validation.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "validation.svg").write_text(figure(cells) + "\n", encoding="utf-8")
    for c in cells:
        print(
            f"prev {c.prevalence:4.2f} n {c.n:>6}: type I {c.type_i_error:.4f}  "
            f"power {c.power:.3f}  coverage {c.coverage:.3f}"
        )
    print("problems:", results["problems"] or "none")


if __name__ == "__main__":
    main()

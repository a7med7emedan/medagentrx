# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Build the README and documentation figures from the synthetic demo.

Run from the repository root:
    uv run python scripts/make_figures.py --out docs/assets

Figures are deterministic: the demo uses fixed seeds, and matplotlib writes
SVG with a fixed hash salt and no dates. CI regenerates them and fails if
any byte differs.
"""

from __future__ import annotations

import argparse
import io
import json
import tempfile
from pathlib import Path
from typing import Any

import matplotlib as mpl
from matplotlib.backends.backend_svg import FigureCanvasSVG
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from medagentrx.demo.cohort import make_cohort
from medagentrx.demo.scenarios import run_scenario
from medagentrx.ledger import read_entries
from medagentrx.report.build import figures
from medagentrx.report.figures import AMBER, GREY, SLATE, TEAL, SvgFigure, clean_svg
from medagentrx.report.json_report import report_dict

NAMESPACES = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
# REUSE-IgnoreStart
HEADER = (
    "<!-- SPDX-FileCopyrightText: 2026 Ahmed Hemedan -->\n"
    "<!-- SPDX-License-Identifier: Apache-2.0 -->\n"
)
# REUSE-IgnoreEnd


def standalone(svg: str) -> str:
    """Inline report SVG made into a file an <img> tag can show."""
    return HEADER + svg.replace("<svg ", "<svg " + NAMESPACES, 1) + "\n"


def _report_figures(name: str, out: Path, cohort: Any) -> dict[str, SvgFigure]:  # noqa: ANN401
    result = run_scenario(name, out, cohort=cohort)
    last = result.steps[-1].evaluation
    assert last is not None  # noqa: S101
    entries = read_entries(result.directory / "ledger.jsonl")
    return {f.key: f for f in figures(report_dict(last), entries)}


def architecture() -> SvgFigure:
    """Inputs, checks, statistics, ledger and outputs, as in the docs diagram."""
    boxes = {
        "plan": (0.02, 0.72, "change-plan.yaml\nthe approved plan", TEAL),
        "data": (0.02, 0.42, "Predictions\nreference, anchor,\ncandidate", SLATE),
        "meta": (0.02, 0.12, "Training manifest\nand model metadata", SLATE),
        "validator": (0.25, 0.72, "Plan validator\nJSON Schema and\npydantic", GREY),
        "loaders": (0.25, 0.27, "Loaders\nsize limits and\nschema checks", GREY),
        "engine": (0.48, 0.47, "Check engine\nPLAN, DATA, PERF,\nLIFE, DOC", TEAL),
        "stats": (0.48, 0.12, "Statistics\nDeLong, bootstrap,\ncalibration, net benefit", GREY),
        "ledger": (0.48, 0.72, "Decision ledger\nhash-chained JSONL", AMBER),
        "verdict": (0.72, 0.47, "Verdict\nACCEPTED, FAILED,\nOUTSIDE_PLAN", TEAL),
        "outputs": (0.72, 0.12, "Reports\nHTML, JSON, Markdown,\nJUnit", GREY),
        "document": (0.72, 0.72, "PCCP document\nand dashboard", GREY),
    }
    size = (0.2, 0.16)
    arrows = [
        ("plan", "validator"),
        ("data", "loaders"),
        ("meta", "loaders"),
        ("validator", "engine"),
        ("loaders", "engine"),
        ("engine", "stats"),
        ("engine", "verdict"),
        ("ledger", "engine"),
        ("engine", "ledger"),
        ("verdict", "outputs"),
        ("ledger", "document"),
    ]
    with mpl.rc_context({"svg.fonttype": "path", "svg.hashsalt": "medagentrx", "font.size": 8.5}):
        fig = Figure(figsize=(9.6, 4.6))
        FigureCanvasSVG(fig)
        ax = fig.add_axes((0, 0, 1, 1))
        ax.set_xlim(0, 0.94)
        ax.set_ylim(0, 1.08)
        ax.axis("off")
        for x, y, label, colour in boxes.values():
            ax.add_patch(
                FancyBboxPatch(
                    (x, y),
                    *size,
                    boxstyle="round,pad=0.008,rounding_size=0.02",
                    facecolor="white",
                    edgecolor=colour,
                    linewidth=1.8,
                )
            )
            ax.text(x + size[0] / 2, y + size[1] / 2, label, ha="center", va="center", color=SLATE)

        def anchor(key: str, toward: str) -> tuple[float, float]:
            x, y, *_ = boxes[key]
            tx, ty, *_ = boxes[toward]
            cx, cy = x + size[0] / 2, y + size[1] / 2
            if abs(tx - x) > 0.05:
                return (x + size[0] if tx > x else x, cy)
            return (cx, y + size[1] if ty > y else y)

        for start, end in arrows:
            a, b = anchor(start, end), anchor(end, start)
            if (start, end) == ("ledger", "engine"):
                a, b = (a[0] - 0.03, a[1]), (b[0] - 0.03, b[1])
            if (start, end) == ("engine", "ledger"):
                a, b = (a[0] + 0.03, a[1]), (b[0] + 0.03, b[1])
            ax.add_patch(
                FancyArrowPatch(
                    a,
                    b,
                    arrowstyle="-|>",
                    mutation_scale=12,
                    color=GREY,
                    linewidth=1.1,
                    shrinkA=2,
                    shrinkB=2,
                )
            )
        # The plan document is rendered from the validated plan: an arc over the ledger.
        vx, vy, *_ = boxes["validator"]
        dx, dy, *_ = boxes["document"]
        ax.add_patch(
            FancyArrowPatch(
                (vx + size[0] / 2, vy + size[1]),
                (dx + size[0] / 2, dy + size[1]),
                connectionstyle="arc3,rad=-0.25",
                arrowstyle="-|>",
                mutation_scale=12,
                color=TEAL,
                linewidth=1.1,
                shrinkA=2,
                shrinkB=2,
            )
        )
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", metadata={"Date": None, "Creator": None})
    alt = (
        "Architecture: the change plan, prediction files, training manifest and model metadata "
        "are validated and loaded, checked by the engine with the statistics core and the "
        "decision ledger, and give one verdict with HTML, JSON, Markdown and JUnit reports."
    )
    return SvgFigure("architecture", "Architecture", clean_svg(buffer.getvalue()), alt)


def main() -> None:
    """Run the needed demo scenarios and write every figure."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cohort = make_cohort()
    alt_text: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        creep = _report_figures("bio-creep", work, cohort)
        harm = _report_figures("subgroup-harm", work, cohort)
        good = _report_figures("good-update", work, cohort)
        chosen = {
            "figure-timeline": creep["timeline"],
            "figure-forest": harm["forest"],
            "figure-calibration": good["calibration"],
            "figure-decision": good["decision"],
            "figure-architecture": architecture(),
        }
        for name, figure in chosen.items():
            (args.out / f"{name}.svg").write_text(standalone(figure.svg), encoding="utf-8")
            alt_text[name] = figure.alt
    (args.out / "figures.json").write_text(json.dumps(alt_text, indent=2) + "\n", encoding="utf-8")
    for name in alt_text:
        print(f"wrote {args.out / name}.svg")


if __name__ == "__main__":
    main()

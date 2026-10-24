# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Report figures as inline SVG.

Figures are drawn by matplotlib with text as paths, so no font is loaded and
no input text appears as markup. The SVG is reduced to plain elements: the
XML declaration, document type, comments, metadata and namespace
declarations are removed, so a report contains no external reference. Fixed
hash salts and no dates make the output byte-identical for the same input.

Every figure uses shape as well as colour to show a verdict, so it stays
readable in greyscale.

The DejaVu Sans files that ship with matplotlib are registered by path. The
figures then never depend on the user's font cache, which can be stale or
incomplete after a virtual environment is rebuilt.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.backends.backend_svg import FigureCanvasSVG
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

for _font in sorted((Path(mpl.get_data_path()) / "fonts" / "ttf").glob("DejaVuSans*.ttf")):
    font_manager.fontManager.addfont(str(_font))

TEAL = "#0F766E"
SLATE = "#1E293B"
AMBER = "#F59E0B"
RED = "#B91C1C"
GREEN = "#15803D"
GREY = "#64748B"
LIGHT = "#E2E8F0"

VERDICT_STYLE = {
    "ACCEPTED": (GREEN, "o"),
    "FAILED": (RED, "s"),
    "OUTSIDE_PLAN": (AMBER, "^"),
}

_RC: Any = {
    "svg.fonttype": "path",
    "svg.hashsalt": "medagentrx",
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.edgecolor": GREY,
    "axes.labelcolor": SLATE,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlecolor": SLATE,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": SLATE,
    "ytick.color": SLATE,
    "legend.frameon": False,
    "path.simplify": False,
}


def signed(value: float, digits: int) -> str:
    """Format with a sign, never showing a negative zero."""
    rounded = round(value, digits) + 0.0
    return f"{rounded:+.{digits}f}"


@dataclass(frozen=True)
class SvgFigure:
    """An inline SVG figure and its text alternative."""

    key: str
    title: str
    svg: str
    alt: str


_REMOVE = [
    re.compile(r"<\?xml[^>]*\?>\s*", re.S),
    re.compile(r"<!DOCTYPE[^>]*>\s*", re.S),
    re.compile(r"<!--.*?-->\s*", re.S),
    re.compile(r"<metadata>.*?</metadata>\s*", re.S),
    re.compile(r'\s+xmlns(:\w+)?="[^"]*"'),
]


def clean_svg(svg: str) -> str:
    """Reduce matplotlib SVG to inline markup without external references."""
    for pattern in _REMOVE:
        svg = pattern.sub("", svg)
    svg = re.sub(r"<svg ", '<svg role="img" focusable="false" ', svg, count=1)
    if "<script" in svg.lower() or "http" in svg.lower():  # pragma: no cover  # defensive
        raise ValueError("figure SVG contains a script or an external reference")
    return "\n".join(line.rstrip() for line in svg.strip().splitlines())


def _render(figure: Figure) -> str:
    buffer = io.StringIO()
    FigureCanvasSVG(figure)
    figure.savefig(buffer, format="svg", metadata={"Date": None, "Creator": None})
    return clean_svg(buffer.getvalue())


def _figure(width: float = 6.4, height: float = 3.4) -> Figure:
    return Figure(figsize=(width, height), layout="constrained")


def timeline(
    points: Sequence[dict[str, Any]], *, anchor_auc: float | None, budget: float
) -> SvgFigure:
    """Figure 1: AUROC with interval per version, the anchor and the drift budget.

    Args:
        points: Per version: ``version``, ``verdict`` and, when assessed, ``auc``,
            ``ci_lower`` and ``ci_upper``.
        anchor_auc: AUROC of the anchor, or None if unknown.
        budget: Largest allowed drop below the anchor.
    """
    with mpl.rc_context(_RC):
        fig = _figure()
        ax = fig.add_subplot()
        xs = list(range(len(points)))
        if anchor_auc is not None:
            ax.axhline(anchor_auc, color=TEAL, linewidth=1.2, label="Anchor AUROC")
            ax.axhspan(
                anchor_auc - budget, anchor_auc, color=TEAL, alpha=0.08, label="Drift budget"
            )
            ax.axhline(anchor_auc - budget, color=TEAL, linewidth=0.8, linestyle="--")
        assessed = [(x, p) for x, p in zip(xs, points, strict=True) if p.get("auc") is not None]
        if assessed:
            ax.plot(
                [x for x, _ in assessed], [p["auc"] for _, p in assessed], color=GREY, linewidth=0.8
            )
        seen: set[str] = set()
        for x, p in assessed:
            colour, marker = VERDICT_STYLE.get(p["verdict"], (GREY, "o"))
            ax.errorbar(
                x,
                p["auc"],
                yerr=[[p["auc"] - p["ci_lower"]], [p["ci_upper"] - p["auc"]]],
                fmt=marker,
                color=colour,
                markersize=7,
                capsize=3,
                label=p["verdict"] if p["verdict"] not in seen else None,
            )
            seen.add(p["verdict"])
        for x, p in zip(xs, points, strict=True):
            if p.get("auc") is None:
                colour, marker = VERDICT_STYLE.get(p["verdict"], (GREY, "o"))
                ax.plot(
                    [x],
                    [0.0],
                    marker=marker,
                    color=colour,
                    markersize=7,
                    clip_on=False,
                    transform=ax.get_xaxis_transform(),
                    label=p["verdict"] if p["verdict"] not in seen else None,
                )
                seen.add(p["verdict"])
        ax.set_xticks(xs, [str(p["version"]) for p in points])
        ax.set_xlabel("Model version")
        ax.set_ylabel("AUROC (95% CI)")
        ax.set_title("Update timeline")
        ax.legend(loc="lower left", fontsize=8, ncols=3)
        svg = _render(fig)
    described = ", ".join(
        f"{p['version']} {p['verdict']}"
        + (f" AUROC {p['auc']:.3f}" if p.get("auc") is not None else "")
        for p in points
    )
    anchor_text = "" if anchor_auc is None else f" Anchor AUROC {anchor_auc:.3f}, budget {budget}."
    return SvgFigure(
        "timeline", "Update timeline", svg, f"AUROC by version: {described}.{anchor_text}"
    )


def levey_jennings(
    runs: Sequence[dict[str, Any]], *, mean: float | None, sd: float | None
) -> SvgFigure:
    """Levey-Jennings chart of the QC run bias, oldest run first.

    Args:
        runs: Per run: ``bias``, ``in_control`` and optionally ``current`` and
            ``rules`` (the rules that fired on it).
        mean: Target bias, or None while the baseline is being collected.
        sd: SD of the bias, or None while the baseline is being collected.
    """
    with mpl.rc_context(_RC):
        fig = _figure(6.4, 3.2)
        ax = fig.add_subplot()
        xs = list(range(1, len(runs) + 1))
        scaled = mean is not None and sd is not None and sd > 0.0
        if scaled:
            values = [(r["bias"] - mean) / sd for r in runs]
            for k, style in ((3, ":"), (2, "--"), (1, "-")):
                for sign in (1, -1):
                    ax.axhline(
                        sign * k, color=RED if k == 3 else GREY, linewidth=0.8, linestyle=style
                    )
            ax.axhline(0.0, color=TEAL, linewidth=1.2)
            ax.set_yticks(
                [-3, -2, -1, 0, 1, 2, 3],
                ["-3 SD", "-2 SD", "-1 SD", "mean", "+1 SD", "+2 SD", "+3 SD"],
            )
            low = min([-3.5, *values])
            high = max([3.5, *values])
            ax.set_ylim(low - 0.3, high + 0.3)
            ax.set_ylabel("Run bias")
        else:
            values = [float(r["bias"]) for r in runs]
            ax.axhline(0.0, color=TEAL, linewidth=1.2)
            ax.set_ylabel("Run bias (live minus expected)")
            ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 3))
        ax.plot(xs, values, color=GREY, linewidth=0.8)
        seen: set[str] = set()
        for x, value, run in zip(xs, values, runs, strict=True):
            if not run["in_control"]:
                label, colour, marker = "Rejected", RED, "s"
            elif run.get("rules"):
                label, colour, marker = "Warning", AMBER, "^"
            else:
                label, colour, marker = "In control", GREEN, "o"
            size = 9 if run.get("current") else 6
            ax.plot(
                [x],
                [value],
                marker=marker,
                color=colour,
                markersize=size,
                linestyle="none",
                label=label if label not in seen else None,
            )
            seen.add(label)
            if run.get("current") and run.get("rules"):
                ax.annotate(
                    ", ".join(run["rules"]),
                    (x, value),
                    textcoords="offset points",
                    xytext=(6, 6),
                    fontsize=8,
                    color=SLATE,
                )
        ax.set_xlabel("QC run")
        ax.set_xlim(0.5, max(len(runs), 1) + 0.5)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title("Levey-Jennings chart of the run bias")
        ax.legend(loc="lower left", fontsize=8, ncols=3)
        svg = _render(fig)
    rejected = sum(1 for r in runs if not r["in_control"])
    scale = "in SD from the target mean" if scaled else "before the baseline is complete"
    current = next((r for r in runs if r.get("current")), None)
    fired = (
        f" The latest run fired {', '.join(current['rules'])}."
        if current and current.get("rules")
        else ""
    )
    alt = f"Run bias of {len(runs)} QC runs {scale}; {rejected} rejected.{fired}"
    return SvgFigure("levey_jennings", "Levey-Jennings chart", svg, alt)


def forest(subgroups: Sequence[dict[str, Any]], *, max_drop: float) -> SvgFigure:
    """Figure 2: change in AUROC per subgroup with its interval at the level it was tested."""
    rows = list(reversed(subgroups))
    with mpl.rc_context(_RC):
        fig = _figure(6.4, max(2.2, 0.32 * len(rows) + 1.0))
        ax = fig.add_subplot()
        ax.axvline(0.0, color=GREY, linewidth=0.8)
        ax.axvline(
            -max_drop, color=RED, linewidth=1.0, linestyle="--", label=f"Tolerance -{max_drop}"
        )
        for y, g in enumerate(rows):
            if g.get("status") == "insufficient":
                ax.plot([0.0], [y], marker="x", color=GREY)
                continue
            colour, marker = (GREEN, "o") if g["status"] == "pass" else (RED, "s")
            ax.errorbar(
                g["delta"],
                y,
                xerr=[[g["delta"] - g["ci_lower"]], [g["ci_upper"] - g["delta"]]],
                fmt=marker,
                color=colour,
                capsize=3,
                markersize=6,
            )
        ax.set_yticks(range(len(rows)), [f"{g['column']} = {g['level']}" for g in rows])
        ax.set_xlabel("AUROC change vs previous (adjusted CI)")
        ax.set_title("Subgroups")
        ax.legend(loc="lower right", fontsize=8)
        svg = _render(fig)
    described = "; ".join(
        f"{g['column']}={g['level']} "
        + (
            "insufficient evidence"
            if g.get("status") == "insufficient"
            else f"{g['delta']:+.3f} {g['status']}"
        )
        for g in subgroups
    )
    return SvgFigure(
        "forest", "Subgroup forest plot", svg, f"AUROC change by subgroup: {described}."
    )


def calibration_curves(
    curves: dict[str, dict[str, list[float]]], summary: dict[str, Any]
) -> SvgFigure:
    """Figure 3: observed against predicted risk for previous and candidate."""
    with mpl.rc_context(_RC):
        fig = _figure(4.6, 4.0)
        ax = fig.add_subplot()
        top = max([*curves["candidate"]["predicted"], *curves["candidate"]["observed"], 0.1]) * 1.05
        ax.plot([0, top], [0, top], color=GREY, linewidth=0.8, linestyle=":", label="Perfect")
        styles = {"previous": (GREY, "s", "--"), "candidate": (TEAL, "o", "-")}
        for name in ("previous", "candidate"):
            colour, marker, line = styles[name]
            label = name.capitalize()
            if name == "candidate":
                label += (
                    f" (slope {summary['slope']:.2f}, intercept {signed(summary['intercept'], 2)})"
                )
            ax.plot(
                curves[name]["predicted"],
                curves[name]["observed"],
                marker=marker,
                linestyle=line,
                color=colour,
                markersize=5,
                label=label,
            )
        ax.set_xlim(0, top)
        ax.set_ylim(0, top)
        ax.set_xlabel("Predicted risk")
        ax.set_ylabel("Observed risk")
        ax.set_title("Calibration")
        ax.legend(loc="upper left", fontsize=8)
        svg = _render(fig)
    alt = (
        f"Calibration of the candidate: slope {summary['slope']:.2f}, "
        f"intercept {signed(summary['intercept'], 2)}, "
        "against the previous version and the diagonal."
    )
    return SvgFigure("calibration", "Calibration curves", svg, alt)


def decision_curves(curve: dict[str, Any]) -> SvgFigure:
    """Figure 4: net benefit across thresholds, plan thresholds marked."""
    with mpl.rc_context(_RC):
        fig = _figure()
        ax = fig.add_subplot()
        t = curve["thresholds"]
        ax.axhline(0.0, color=GREY, linewidth=0.8, label="Treat none")
        ax.plot(t, curve["treat_all"], color=GREY, linestyle=":", label="Treat all")
        ax.plot(t, curve["previous"], color=GREY, linestyle="--", label="Previous")
        ax.plot(t, curve["candidate"], color=TEAL, linewidth=1.6, label="Candidate")
        for threshold in curve["plan_thresholds"]:
            ax.axvline(threshold, color=AMBER, linewidth=0.8, linestyle="-.")
        top = max(max(curve["candidate"]), max(curve["previous"]), 0.01)
        ax.set_ylim(-0.25 * top, top * 1.15)
        ax.set_xlabel("Risk threshold")
        ax.set_ylabel("Net benefit")
        ax.set_title("Decision curve")
        ax.legend(loc="upper right", fontsize=8)
        svg = _render(fig)
    marked = ", ".join(f"{x:g}" for x in curve["plan_thresholds"])
    return SvgFigure(
        "decision",
        "Decision curve",
        svg,
        "Net benefit of candidate, previous version, treat all and treat none; "
        f"plan thresholds {marked}.",
    )


def budget_gauges(budgets: Sequence[tuple[str, float, float, str]]) -> SvgFigure:
    """Figure 5: share of each plan budget used, including this evaluation.

    Args:
        budgets: ``(label, used, total, text)`` per budget.
    """
    with mpl.rc_context(_RC):
        fig = _figure(6.4, 0.55 * len(budgets) + 0.9)
        ax = fig.add_subplot()
        for y, (_, used, total, _) in enumerate(budgets):
            share = 0.0 if total <= 0 else min(used / total, 1.0)
            colour = RED if share >= 1.0 else (AMBER if share >= 0.75 else TEAL)
            ax.barh(y, 1.0, color=LIGHT, height=0.55)
            ax.barh(y, share, color=colour, height=0.55, hatch="//" if share >= 0.75 else None)
        ax.set_yticks(range(len(budgets)), [f"{label}: {text}" for label, _, _, text in budgets])
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
        ax.invert_yaxis()
        ax.set_title("Plan budgets used")
        svg = _render(fig)
    alt = "; ".join(f"{label} {text}" for label, _, _, text in budgets)
    return SvgFigure("budgets", "Plan budgets", svg, f"Budgets used: {alt}.")

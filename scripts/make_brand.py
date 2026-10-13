# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Build the MedAgentRx logo variants and social preview.

The mark is a prescription sign (Rx). Its upright stroke is a gate post, the
stroke that crosses the R's leg is a confidence-interval whisker, and a small
check mark sits above, all in a rounded square. The wordmark is set in Inter
(SIL Open Font License 1.1) and converted to outlines, so no font is loaded.

Run from the repository root, with the Inter 4.1 release unpacked somewhere:
    uv run python scripts/make_brand.py --inter /path/to/Inter-4.1/extras/ttf

Every colour pairing used is checked for WCAG AA contrast.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from matplotlib.font_manager import FontProperties
from matplotlib.path import Path as MplPath
from matplotlib.textpath import TextPath

TEAL = "#0F766E"
SLATE = "#1E293B"
AMBER = "#F59E0B"
AMBER_DARK = "#B45309"
AMBER_LIGHT = "#FCD34D"
WHITE = "#FFFFFF"
DARK_BG = "#0F172A"
TAGLINE = (
    "The prescription for self-improving medical AI. Every model update, by an engineer, "
    "a pipeline or an AI agent, is checked against its approved change plan."
)
# REUSE-IgnoreStart
HEADER = (
    "<!-- SPDX-FileCopyrightText: 2026 Ahmed Hemedan -->\n"
    "<!-- SPDX-License-Identifier: Apache-2.0 -->\n"
)
# REUSE-IgnoreEnd
SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" '


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Pairings used, with the WCAG AA minimum for their size (large text and graphics: 3.0).
PAIRINGS = [
    ("white on teal (mark)", WHITE, TEAL, 3.0),
    ("light amber on teal (whisker and check)", AMBER_LIGHT, TEAL, 3.0),
    ("slate on white (wordmark)", SLATE, WHITE, 4.5),
    ("dark amber on white (Rx in wordmark)", AMBER_DARK, WHITE, 4.5),
    ("white on dark (wordmark, dark variant)", WHITE, DARK_BG, 4.5),
    ("amber on dark (Rx, dark variant)", AMBER, DARK_BG, 4.5),
    ("teal on white (verdict accents)", TEAL, WHITE, 4.5),
]


def mark(fill: str = TEAL, stroke: str = WHITE, accent: str = AMBER_LIGHT) -> str:
    """The Rx gate mark in a 64 by 64 box."""
    return (
        f'<rect width="64" height="64" rx="14" fill="{fill}"/>'
        f'<g fill="none" stroke-linecap="round" stroke-linejoin="round">'
        # Gate post: the upright stroke of the R.
        f'<path d="M19 13 V51" stroke="{stroke}" stroke-width="7"/>'
        # Bowl of the R.
        f'<path d="M19 13 H30 A9.5 9.5 0 0 1 30 32 H19" stroke="{stroke}" stroke-width="6"/>'
        # Leg of the R.
        f'<path d="M28 32 L45 52" stroke="{stroke}" stroke-width="6"/>'
        # Confidence-interval whisker crossing the leg: a bar with end caps.
        f'<path d="M30 45 H50 M30 41 V49 M50 41 V49" stroke="{accent}" stroke-width="3.5"/>'
        # Check mark.
        f'<path d="M41 17 L45 21 L53 12" stroke="{accent}" stroke-width="3.5"/>'
        "</g>"
    )


def _path_d(path: MplPath, x0: float, baseline: float, scale: float) -> str:
    parts: list[str] = []
    codes = path.codes if path.codes is not None else [MplPath.LINETO] * len(path.vertices)
    vertices = path.vertices
    i = 0
    while i < len(vertices):
        code = codes[i]

        def point(j: int) -> str:
            x, y = vertices[j]
            return f"{x0 + x * scale:.2f} {baseline - y * scale:.2f}"

        if code == MplPath.MOVETO:
            parts.append("M" + point(i))
            i += 1
        elif code == MplPath.LINETO:
            parts.append("L" + point(i))
            i += 1
        elif code == MplPath.CURVE3:
            parts.append("Q" + point(i) + " " + point(i + 1))
            i += 2
        elif code == MplPath.CURVE4:
            parts.append("C" + point(i) + " " + point(i + 1) + " " + point(i + 2))
            i += 3
        else:
            parts.append("Z")
            i += 1
    return "".join(parts)


def outlined(text: str, font: Path, x: float, baseline: float, size: float) -> tuple[str, float]:
    """SVG path data for ``text`` and its advance width."""
    path = TextPath((0, 0), text, size=100, prop=FontProperties(fname=font))
    scale = size / 100
    width = path.get_extents().x1 * scale
    return _path_d(path, x, baseline, scale), width


def lockup(font: Path, *, word: str, rx: str, background: str | None) -> str:
    """Mark plus wordmark."""
    first, w1 = outlined("MedAgent", font, 80, 44, 34)
    second, w2 = outlined("Rx", font, 80 + w1 + 1, 44, 34)
    width = int(80 + w1 + w2 + 12)
    back = f'<rect width="{width}" height="64" fill="{background}"/>' if background else ""
    return (
        HEADER + SVG_OPEN + f'viewBox="0 0 {width} 64" width="{width}" height="64" '
        f'role="img" aria-label="MedAgentRx">{back}{mark()}'
        f'<path d="{first}" fill="{word}"/><path d="{second}" fill="{rx}"/></svg>\n'
    )


def write_all(font_dir: Path, assets: Path) -> None:
    """Write every brand asset into ``assets``."""
    bold = font_dir / "Inter-Bold.ttf"
    semibold = font_dir / "Inter-SemiBold.ttf"
    assets.mkdir(parents=True, exist_ok=True)
    for name, fg, bg, minimum in PAIRINGS:
        ratio = contrast(fg, bg)
        if ratio < minimum:
            raise SystemExit(f"contrast too low for {name}: {ratio:.2f} < {minimum}")
    standalone = SVG_OPEN + 'viewBox="0 0 64 64" role="img" aria-label="MedAgentRx">'
    (assets / "logo-mark.svg").write_text(
        HEADER + standalone + mark() + "</svg>\n", encoding="utf-8"
    )
    favicon = SVG_OPEN + 'viewBox="0 0 64 64" width="32" height="32">'
    (assets / "favicon.svg").write_text(HEADER + favicon + mark() + "</svg>\n", encoding="utf-8")
    (assets / "logo.svg").write_text(
        lockup(bold, word=SLATE, rx=AMBER_DARK, background=None), encoding="utf-8"
    )
    (assets / "logo-dark.svg").write_text(
        lockup(bold, word=WHITE, rx=AMBER, background=DARK_BG), encoding="utf-8"
    )
    mono = lockup(bold, word=SLATE, rx=SLATE, background=None).replace(
        mark(), mark(SLATE, WHITE, WHITE)
    )
    (assets / "logo-mono.svg").write_text(mono, encoding="utf-8")
    social_preview(bold, semibold, assets / "social-preview.png")


def social_preview(bold: Path, semibold: Path, target: Path) -> None:
    """1280 by 640 PNG: mark, wordmark and tagline."""
    from matplotlib.figure import Figure
    from matplotlib.patches import PathPatch
    from matplotlib.transforms import Affine2D

    fig = Figure(figsize=(12.8, 6.4), dpi=100)
    fig.patch.set_facecolor(DARK_BG)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1280)
    ax.set_ylim(640, 0)
    ax.axis("off")
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    FigureCanvasAgg(fig)

    def text(content: str, font: Path, x: float, y: float, size: float, colour: str) -> float:
        path = TextPath((0, 0), content, size=size, prop=FontProperties(fname=font))
        transform = Affine2D().scale(1, -1).translate(x, y)
        ax.add_patch(PathPatch(transform.transform_path(path), facecolor=colour, edgecolor="none"))
        return float(path.get_extents().x1)

    from matplotlib.patches import Circle, FancyBboxPatch

    ax.add_patch(
        FancyBboxPatch((96, 128), 192, 192, boxstyle="round,pad=0,rounding_size=42", color=TEAL)
    )
    s = 3.0

    def line(points: list[tuple[float, float]], colour: str, width: float) -> None:
        xs = [96 + p[0] * s for p in points]
        ys = [128 + p[1] * s for p in points]
        ax.plot(
            xs, ys, color=colour, linewidth=width, solid_capstyle="round", solid_joinstyle="round"
        )

    import numpy as np

    line([(19, 13), (19, 51)], WHITE, 14)
    angles = np.linspace(-np.pi / 2, np.pi / 2, 30)
    bowl = (
        [(19, 13), (30, 13)]
        + [(30 + 9.5 * np.cos(a), 22.5 + 9.5 * np.sin(a)) for a in angles]
        + [(19, 32)]
    )
    line(bowl, WHITE, 12)
    line([(28, 32), (45, 52)], WHITE, 12)
    line([(30, 45), (50, 45)], AMBER_LIGHT, 7)
    line([(30, 41), (30, 49)], AMBER_LIGHT, 7)
    line([(50, 41), (50, 49)], AMBER_LIGHT, 7)
    line([(41, 17), (45, 21), (53, 12)], AMBER_LIGHT, 7)
    del Circle
    width = text("MedAgent", bold, 336, 262, 104, WHITE)
    text("Rx", bold, 336 + width + 4, 262, 104, AMBER)
    words = TAGLINE.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) > 62:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    for i, content in enumerate(lines):
        text(content, semibold, 96, 420 + i * 46, 34, "#CBD5E1")
    fig.savefig(target, facecolor=DARK_BG, metadata={"Software": None})


def main() -> None:
    """Parse arguments and write the assets."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--inter",
        type=Path,
        required=True,
        help="Folder with Inter-Bold.ttf and Inter-SemiBold.ttf.",
    )
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    write_all(args.inter, args.out)
    for name, fg, bg, minimum in PAIRINGS:
        print(f"{name}: {contrast(fg, bg):.2f} (minimum {minimum})")


if __name__ == "__main__":
    main()

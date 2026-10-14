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
import json
import tempfile
from pathlib import Path
from typing import Any

from medagentrx.demo.cohort import make_cohort
from medagentrx.demo.scenarios import run_scenario
from medagentrx.ledger import read_entries
from medagentrx.report.build import figures
from medagentrx.report.figures import SvgFigure
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
        }
        for name, figure in chosen.items():
            (args.out / f"{name}.svg").write_text(standalone(figure.svg), encoding="utf-8")
            alt_text[name] = figure.alt
    (args.out / "figures.json").write_text(json.dumps(alt_text, indent=2) + "\n", encoding="utf-8")
    for name in alt_text:
        print(f"wrote {args.out / name}.svg")


if __name__ == "__main__":
    main()

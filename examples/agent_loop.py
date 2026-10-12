# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""An AutoML-style loop that improves a model only inside the approved plan.

The loop keeps proposing retrained candidates. The guard answers each one
with a single noisy pass or fail bit and spends one look at the locked test
set. When the plan's look budget is used up, the guard refuses and the loop
stops. A candidate the agent likes still needs a formal `medagentrx check`
before release.

Run from the repository root (synthetic data only):
    uv run python examples/agent_loop.py --out agent-demo
"""

from __future__ import annotations

import argparse
from pathlib import Path

from medagentrx.demo.cohort import make_cohort
from medagentrx.demo.scenarios import build_peeking_agent
from medagentrx.guard import Guard


def run(out: Path, replicates: int = 2000) -> list[str]:
    """Run the loop and return one line per submission."""
    proposals = build_peeking_agent(make_cohort(), out / "candidates")
    first = proposals[0]["inputs"]
    guard = Guard(
        first["plan"],
        out / "ledger.jsonl",
        "thresholdout",
        previous=first["previous"],
        n_replicates=replicates,
    )
    print("The agent may make:", ", ".join(m.id for m in guard.allowed_modifications()))
    log = []
    for proposal in proposals:
        files = proposal["inputs"]
        decision = guard.submit(
            files["candidate"], files["model_meta"], manifest=files["manifest"], now=proposal["now"]
        )
        name = proposal["directory"].name
        line = f"{name}: {decision.reason} ({decision.looks_remaining} looks left)"
        print(line)
        log.append(line)
        if decision.failed_checks:
            print("The guard refused. Stopping the search.")
            break
    return log


def main() -> None:
    """Parse arguments and run the loop."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("agent-demo"))
    parser.add_argument("--replicates", type=int, default=2000)
    args = parser.parse_args()
    run(args.out, args.replicates)


if __name__ == "__main__":
    main()

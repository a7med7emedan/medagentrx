# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Write the synthetic files of examples/sepsis-risk from the good-update scenario.

It also writes the deployment QC files in qc/ and the plan's deployment_qc block.

Run from the repository root:
    uv run python scripts/make_example.py

The example plan keeps its comments; only its locked test-set fingerprint is
set from the synthetic test set.
"""

import re
import shutil
import tempfile
from pathlib import Path

import numpy as np

from medagentrx.demo.cohort import Cohort, make_cohort
from medagentrx.demo.qc_scenarios import QC_NOISE, prepare_control_set
from medagentrx.demo.scenarios import build_good_update, locked_fingerprint, write_parquet
from medagentrx.qc import qc_block_yaml, qc_init

EXAMPLE = Path("examples/sepsis-risk")
FILES = ("candidate.parquet", "previous.parquet", "anchor.parquet", "train_manifest.parquet")


def main() -> None:
    """Regenerate the example files."""
    cohort = make_cohort()
    with tempfile.TemporaryDirectory() as tmp:
        built = build_good_update(cohort, Path(tmp) / "good-update")[0]["directory"]
        for name in FILES:
            shutil.copyfile(built / name, EXAMPLE / name)
        meta = (built / "model.yaml").read_text(encoding="utf-8")
    # REUSE-IgnoreStart
    header = (
        "# SPDX-FileCopyrightText: 2026 Ahmed Hemedan\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "#\n"
        "# Metadata of candidate version 2.1.0 in the synthetic example.\n"
    )
    # REUSE-IgnoreEnd
    (EXAMPLE / "model.yaml").write_text(header + meta, encoding="utf-8")
    plan_path = EXAMPLE / "change-plan.yaml"
    plan = plan_path.read_text(encoding="utf-8")
    plan = re.sub(
        r'(locked_test_set:\n(?:    #.*\n)*    sha256: )"[0-9a-f]{64}"',
        rf'\1"{locked_fingerprint(cohort)}"',
        plan,
    )
    plan = plan.replace(
        "    # Provisional. Replaced by the fingerprint of the synthetic demo test set.\n",
        "    # Fingerprint of the synthetic test set in this folder (medagentrx fingerprint).\n",
    )
    plan = plan.split(QC_MARKER)[0].rstrip("\n") + "\n\n" + _qc_example(cohort)
    plan_path.write_text(plan, encoding="utf-8")


QC_MARKER = "# Deployment QC"


def _qc_example(cohort: Cohort) -> str:
    """Write the qc/ folder and return the plan's deployment_qc block."""
    folder = EXAMPLE / "qc"
    folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        control = prepare_control_set(cohort, Path(tmp))
        shutil.copyfile(control.control, folder / "control_inputs.parquet")
        shutil.copyfile(control.expected["2.0.0"][0], folder / "expected-2.0.0.parquet")
        live = control.expected["2.0.0"][1] + np.random.default_rng(2026).normal(
            0.0, QC_NOISE, len(control.ids)
        )
        write_parquet(
            folder / "live-scores.parquet",
            {"row_id": list(control.ids), "y_score": np.clip(live, 0.0, 1.0).tolist()},
        )
    init = qc_init(
        control_inputs=folder / "control_inputs.parquet",
        scores=folder / "expected-2.0.0.parquet",
        version="2.0.0",
        test_set=EXAMPLE / "candidate.parquet",
        manifest=EXAMPLE / "train_manifest.parquet",
    )
    return (
        f"{QC_MARKER}: control samples scored by the live system (medagentrx qc init).\n"
        "# The raw control records stay with the user; the plan keeps fingerprints only.\n"
        + qc_block_yaml(init)
    )


if __name__ == "__main__":
    main()

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Write the synthetic files of examples/sepsis-risk from the good-update scenario.

Run from the repository root:
    uv run python scripts/make_example.py

The example plan keeps its comments; only its locked test-set fingerprint is
set from the synthetic test set.
"""

import re
import shutil
import tempfile
from pathlib import Path

from medagentrx.demo.cohort import make_cohort
from medagentrx.demo.scenarios import build_good_update, locked_fingerprint

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
    plan_path.write_text(plan, encoding="utf-8")


if __name__ == "__main__":
    main()

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Exercise the GitHub Action, GitLab component and pre-commit hook on the example.

The Action's shell step runs for real; a stand-in `docker` runs medagentrx
with the same arguments, because a container engine may not be available.
CI also runs the Action itself with Docker.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

EXAMPLE = {
    "plan": "examples/sepsis-risk/change-plan.yaml",
    "candidate": "examples/sepsis-risk/candidate.parquet",
    "previous": "examples/sepsis-risk/previous.parquet",
    "anchor": "examples/sepsis-risk/anchor.parquet",
    "manifest": "examples/sepsis-risk/train_manifest.parquet",
    "model-meta": "examples/sepsis-risk/model.yaml",
}
CHECK_OPTIONS = {
    "--candidate",
    "--previous",
    "--anchor",
    "--manifest",
    "--model-meta",
    "--ledger",
    "--out",
    "--seed",
    "--replicates",
    "--format",
}
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the Action's step runs in bash")


def _action() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((REPO_ROOT / "action.yml").read_text(encoding="utf-8"))
    return data


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "work"
    for relative in EXAMPLE.values():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    return workspace


def test_action_inputs_mirror_the_check_command() -> None:
    action = _action()
    inputs = set(action["inputs"])
    assert {
        "plan",
        "candidate",
        "previous",
        "anchor",
        "manifest",
        "model-meta",
        "ledger",
        "out",
        "seed",
        "replicates",
        "format",
    } <= inputs
    step = next(s for s in action["runs"]["steps"] if s.get("id") == "check")
    used = set(re.findall(r"(--[a-z-]+) ", step["run"]))
    assert used >= CHECK_OPTIONS
    pinned = [s["uses"] for s in action["runs"]["steps"] if "uses" in s]
    assert all(re.search(r"@[0-9a-f]{40}$", u) for u in pinned)
    assert "--read-only" in step["run"]
    assert "--network none" in step["run"]


@posix_only
@pytest.mark.parametrize(
    ("mutate", "verdict", "code"), [(None, "ACCEPTED", 0), ("bad-meta", "OUTSIDE_PLAN", 2)]
)
def test_action_check_step(tmp_path: Path, mutate: str | None, verdict: str, code: int) -> None:
    workspace = _workspace(tmp_path)
    if mutate == "bad-meta":
        meta = workspace / EXAMPLE["model-meta"]
        meta.write_text(
            meta.read_text(encoding="utf-8").replace("modification_id: M1", "modification_id: M7")
        )
    shim = tmp_path / "bin"
    shim.mkdir()
    medagentrx = shutil.which("medagentrx")
    assert medagentrx is not None
    (shim / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "# Stand-in for docker run: drop the flags and the image, run medagentrx.\n"
        "shift\n"
        'while [ $# -gt 0 ]; do case "$1" in\n'
        "  --rm|--read-only) shift ;;\n"
        "  --tmpfs|--network|--user|--volume|--workdir) shift 2 ;;\n"
        "  *) shift; break ;;\n"
        "esac; done\n"
        f'exec "{medagentrx}" "$@"\n'
    )
    (shim / "docker").chmod(0o755)
    step = next(s for s in _action()["runs"]["steps"] if s.get("id") == "check")
    outputs, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(outputs),
        "GITHUB_STEP_SUMMARY": str(summary),
        "MEDAGENTRX_IMAGE": "",
        "PLAN": EXAMPLE["plan"],
        "CANDIDATE": EXAMPLE["candidate"],
        "PREVIOUS": EXAMPLE["previous"],
        "ANCHOR": EXAMPLE["anchor"],
        "MANIFEST": EXAMPLE["manifest"],
        "MODEL_META": EXAMPLE["model-meta"],
        "LEDGER": "ledger/ledger.jsonl",
        "OUT": "medagentrx-report",
        "SEED": "0",
        "REPLICATES": "200",
        "FORMAT": "html,json,md,junit",
    }
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run([bash, "-e", "-c", step["run"]], cwd=workspace, env=env, check=True)  # noqa: S603
    assert f"verdict={verdict}" in outputs.read_text()
    assert f"exit-code={code}" in outputs.read_text()
    assert summary.read_text().startswith("## MedAgentRx:")
    assert (workspace / "medagentrx-report" / "report.html").exists()
    assert (workspace / "ledger" / "ledger.jsonl").exists()


def test_gitlab_component(tmp_path: Path) -> None:
    spec, jobs = list(
        yaml.safe_load_all((REPO_ROOT / "templates" / "medagentrx.yml").read_text(encoding="utf-8"))
    )
    inputs = spec["spec"]["inputs"]
    assert "default" not in inputs["image"]
    values = {
        **{k: v["default"] for k, v in inputs.items() if "default" in v},
        **EXAMPLE,
        "image": "unused",
        "ledger": "ledger/ledger.jsonl",
        "replicates": 200,
    }
    (job,) = jobs.values()
    assert job["artifacts"]["reports"]["junit"] == "$[[ inputs.out ]]/junit.xml"
    script = re.sub(
        r"\$\[\[ inputs\.([a-z-]+) \]\]", lambda m: str(values[m.group(1)]), job["script"][0]
    )
    workspace = _workspace(tmp_path)
    args = shlex.split(script)
    assert args[:2] == ["medagentrx", "check"]
    medagentrx = shutil.which("medagentrx")
    assert medagentrx is not None
    result = subprocess.run([medagentrx, *args[1:]], cwd=workspace, capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, result.stderr
    assert (workspace / "medagentrx-report" / "junit.xml").exists()


def test_dockerfile_rules() -> None:
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    froms = re.findall(r"^FROM (\S+)", text, re.M)
    assert froms
    assert all("@sha256:" in image for image in froms)
    assert re.search(r"^USER 10001:10001$", text, re.M)
    assert 'ENTRYPOINT ["medagentrx"]' in text
    assert 'org.opencontainers.image.authors="Ahmed Hemedan"' in text

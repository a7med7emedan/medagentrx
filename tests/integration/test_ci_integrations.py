# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Exercise the GitHub Action, GitLab component and pre-commit hook on the example.

The Action's shell step runs for real; a stand-in `docker` runs medagentrx
with the same arguments, because a container engine may not be available.
CI also runs the Action itself with Docker.
"""

import os
import re
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


@posix_only
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
    assert 'medagentrx "$@"' in script
    medagentrx = shutil.which("medagentrx")
    assert medagentrx is not None
    sh = shutil.which("sh")
    assert sh is not None
    env = {**os.environ, "PATH": f"{Path(medagentrx).parent}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(  # noqa: S603
        [sh, "-e", "-c", script], cwd=workspace, capture_output=True, text=True, env=env
    )
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


def test_compose_file() -> None:
    compose = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"demo", "dashboard"}
    hardening = compose["x-hardening"]
    assert hardening["read_only"] is True
    assert hardening["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in hardening["security_opt"]
    assert services["dashboard"]["ports"] == ["127.0.0.1:8765:8765"]
    assert services["dashboard"]["volumes"][0].endswith(":/data:ro")
    assert services["demo"]["network_mode"] == "none"


def test_dockerfile_purges_unused_base_packages() -> None:
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    for package in ("bash", "util-linux", "perl-base", "libsystemd0", "apt"):
        assert f" {package} " in text
    assert "--network" not in text


def _uses(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found.append(value)
            else:
                found += _uses(value)
    elif isinstance(node, list):
        for item in node:
            found += _uses(item)
    return found


def test_every_workflow_action_and_image_is_pinned() -> None:
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert {w.name for w in workflows} >= {
        "ci.yml",
        "codeql.yml",
        "scorecard.yml",
        "release.yml",
        "docs.yml",
    }
    for workflow in [*workflows, REPO_ROOT / "action.yml"]:
        for uses in _uses(yaml.safe_load(workflow.read_text(encoding="utf-8"))):
            if uses.startswith("./"):
                continue
            assert re.search(r"@(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$", uses), (
                f"{workflow.name}: {uses}"
            )
    gitlab = (REPO_ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    for image in re.findall(r"(?:ghcr\.io|docker)[\w./:-]*@sha256:[0-9a-f]+|image: (\S+)", gitlab):
        if image and not image.startswith("$") and "uv:python" not in image:
            assert "@sha256:" in image, image


QC_FILES = {
    "plan": "examples/sepsis-risk/change-plan.yaml",
    "scores": "examples/sepsis-risk/qc/live-scores.parquet",
    "expected": "examples/sepsis-risk/qc/expected-2.0.0.parquet",
    "control-inputs": "examples/sepsis-risk/qc/control_inputs.parquet",
}


def _qc_workspace(tmp_path: Path) -> Path:
    workspace = _workspace(tmp_path)
    for relative in QC_FILES.values():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    return workspace


def _docker_shim(tmp_path: Path) -> Path:
    shim = tmp_path / "bin"
    shim.mkdir()
    medagentrx = shutil.which("medagentrx")
    assert medagentrx is not None
    (shim / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "shift\n"
        'while [ $# -gt 0 ]; do case "$1" in\n'
        "  --rm|--read-only) shift ;;\n"
        "  --tmpfs|--network|--user|--volume|--workdir) shift 2 ;;\n"
        "  *) shift; break ;;\n"
        "esac; done\n"
        f'exec "{medagentrx}" "$@"\n'
    )
    (shim / "docker").chmod(0o755)
    return shim


def test_action_has_a_qc_mode() -> None:
    action = _action()
    assert action["inputs"]["mode"]["default"] == "check"
    assert {"scores", "expected", "model-version", "control-inputs"} <= set(action["inputs"])
    for name in ("candidate", "previous", "anchor", "manifest", "model-meta"):
        assert action["inputs"][name]["default"] == ""


@posix_only
@pytest.mark.parametrize(
    ("version", "verdict", "code"), [("2.0.0", "IN_CONTROL", 0), ("2.1.0", "OUTSIDE_PLAN", 2)]
)
def test_action_qc_step(tmp_path: Path, version: str, verdict: str, code: int) -> None:
    workspace = _qc_workspace(tmp_path)
    step = next(s for s in _action()["runs"]["steps"] if s.get("id") == "check")
    outputs, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{_docker_shim(tmp_path)}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(outputs),
        "GITHUB_STEP_SUMMARY": str(summary),
        "MEDAGENTRX_IMAGE": "",
        "MODE": "qc",
        "PLAN": QC_FILES["plan"],
        "SCORES": QC_FILES["scores"],
        "EXPECTED": QC_FILES["expected"],
        "MODEL_VERSION": version,
        "CONTROL_INPUTS": QC_FILES["control-inputs"],
        "LEDGER": "ledger/ledger.jsonl",
        "OUT": "medagentrx-report",
        "FORMAT": "html,json,md,junit",
    }
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run([bash, "-e", "-c", step["run"]], cwd=workspace, env=env, check=True)  # noqa: S603
    assert f"verdict={verdict}" in outputs.read_text()
    assert f"exit-code={code}" in outputs.read_text()
    assert summary.read_text().startswith("## MedAgentRx QC:")
    bad = {**env, "MODE": "audit"}
    failed = subprocess.run([bash, "-e", "-c", step["run"]], cwd=workspace, env=bad, check=False)  # noqa: S603
    assert failed.returncode == 3


@posix_only
def test_gitlab_component_qc_mode(tmp_path: Path) -> None:
    spec, jobs = list(
        yaml.safe_load_all((REPO_ROOT / "templates" / "medagentrx.yml").read_text(encoding="utf-8"))
    )
    inputs = spec["spec"]["inputs"]
    assert inputs["mode"]["options"] == ["check", "qc"]
    values = {
        **{k: v["default"] for k, v in inputs.items() if "default" in v},
        **QC_FILES,
        "mode": "qc",
        "model-version": "2.0.0",
        "image": "unused",
        "ledger": "ledger/ledger.jsonl",
    }
    (job,) = jobs.values()
    script = re.sub(
        r"\$\[\[ inputs\.([a-z-]+) \]\]", lambda m: str(values[m.group(1)]), job["script"][0]
    )
    workspace = _qc_workspace(tmp_path)
    medagentrx = shutil.which("medagentrx")
    sh = shutil.which("sh")
    assert medagentrx is not None
    assert sh is not None
    env = {**os.environ, "PATH": f"{Path(medagentrx).parent}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(  # noqa: S603
        [sh, "-e", "-c", script], cwd=workspace, capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert "qc verdict: IN_CONTROL" in result.stdout

# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""The versioned documentation build, without running mkdocs."""

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def build_site() -> ModuleType:
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("build_site")


def _git(root: Path, *args: str) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run(  # noqa: S603  # fixed test command
        [git, *args], cwd=root, check=True, capture_output=True
    )


def test_release_tags_keep_the_latest_patch(build_site: ModuleType, tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(
        tmp_path,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "start",
    )
    for tag in ("v0.1.0", "v0.1.2", "v0.1.1", "v0.2.0", "v0.10.0", "v1.0.0rc1", "other"):
        _git(tmp_path, "tag", tag)
    assert build_site.release_tags(tmp_path) == {
        "0.10": "v0.10.0",
        "0.2": "v0.2.0",
        "0.1": "v0.1.2",
    }


def test_root_links_and_versions(build_site: ModuleType, tmp_path: Path) -> None:
    site = tmp_path / "site"
    latest = site / "latest"
    (latest / "qc").mkdir(parents=True)
    (latest / "assets").mkdir()
    (latest / "index.html").write_text("home", "utf-8")
    (latest / "qc" / "index.html").write_text("qc", "utf-8")
    (latest / "404.html").write_text("missing", "utf-8")
    (latest / "assets" / "logo.svg").write_text("<svg/>", "utf-8")
    (site / "versions.json").write_text("[]", "utf-8")
    assert build_site.link_root(site, "latest") == 3
    assert 'url=latest/"' in (site / "index.html").read_text("utf-8")
    assert 'url=../latest/qc/"' in (site / "qc" / "index.html").read_text("utf-8")
    assert 'url=/medagentrx/latest/"' in (site / "404.html").read_text("utf-8")
    assert (site / "assets" / "logo.svg").read_text("utf-8") == "<svg/>"
    build_site.write_versions(site, ["0.2", "0.1"])
    versions = json.loads((site / "versions.json").read_text("utf-8"))
    assert versions == [
        {"version": "0.2", "title": "0.2", "aliases": ["latest"]},
        {"version": "0.1", "title": "0.1", "aliases": []},
    ]


def test_redirect_page_keeps_the_fragment(build_site: ModuleType) -> None:
    page = build_site.redirect_page("../latest/qc/")
    assert 'location.replace("../latest/qc/" + location.hash)' in page
    assert '<link rel="canonical" href="../latest/qc/">' in page

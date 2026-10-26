# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Build the versioned documentation site.

Each released minor version gets its own folder, built from the latest patch
tag of that minor: ``0.1/``, ``0.2/`` and so on, plus ``latest/`` for the
newest. ``versions.json`` drives the version menu of the theme. Every page of
the newest version also gets a redirect at its old address at the site root,
and the root keeps a copy of the image assets, so links made before the site
was versioned keep working.

Run from the repository root:
    python scripts/build_site.py --out site
    python scripts/build_site.py --out site --head 0.2   # also build the working tree

Needs git and uv. Each tag is built with its own locked documentation tools.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

SITE_URL = "https://a7med7emedan.github.io/medagentrx/"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
OVERLAY = "mkdocs.versioned.yml"


def _run(tool: str, *args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    """Run a fixed command of ``git`` or ``uv`` and return its output."""
    executable = shutil.which(tool)
    if executable is None:
        raise SystemExit(f"{tool} is not on the PATH")
    done = subprocess.run(  # noqa: S603  # fixed tools and arguments, no user input
        [executable, *args], cwd=cwd, env=env, check=False, capture_output=True, text=True
    )
    if done.returncode:
        raise SystemExit(f"{tool} {' '.join(args)} failed:\n{done.stdout}{done.stderr}")
    return done.stdout


def release_tags(root: Path) -> dict[str, str]:
    """The latest patch tag of each minor version, by minor label, newest first."""
    listed = _run("git", "tag", "--list", "v*", cwd=root).split()
    best: dict[tuple[int, int], tuple[int, str]] = {}
    for tag in listed:
        match = TAG.match(tag)
        if not match:
            continue
        major, minor, patch = (int(g) for g in match.groups())
        if (major, minor) not in best or patch > best[(major, minor)][0]:
            best[(major, minor)] = (patch, tag)
    return {f"{k[0]}.{k[1]}": best[k][1] for k in sorted(best, reverse=True)}


def _label_key(label: str) -> tuple[int, ...]:
    return tuple(int(part) for part in label.split("."))


def build_version(source: Path, label: str, out: Path, env: Path) -> None:
    """Build the documentation in ``source`` into ``out`` as version ``label``.

    The tools are installed into ``env``, never into the project's own environment.
    """
    overlay = source / OVERLAY
    overlay.write_text(
        "INHERIT: mkdocs.yml\n"
        f"site_url: {SITE_URL}{label}/\n"
        "extra:\n"
        "  version:\n"
        "    provider: mike\n"
        "    default: latest\n",
        encoding="utf-8",
    )
    try:
        _run(
            "uv",
            "sync",
            "--locked",
            "--only-group",
            "docs",
            "--no-install-project",
            "--project",
            str(source),
            cwd=source,
            env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(env)},
        )
        mkdocs = env / ("Scripts" if os.name == "nt" else "bin") / "mkdocs"
        _run(str(mkdocs), "build", "--strict", "-f", str(overlay), "-d", str(out), cwd=source)
    finally:
        overlay.unlink(missing_ok=True)


def redirect_page(target: str) -> str:
    """A page that sends the reader to ``target``, a relative URL."""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>Redirecting</title>\n"
        f'<link rel="canonical" href="{target}">\n'
        f'<meta http-equiv="refresh" content="0; url={target}">\n'
        f'<script>location.replace("{target}" + location.hash)</script>\n'
        "</head>\n"
        f'<body>This page has moved to <a href="{target}">{target}</a>.</body>\n</html>\n'
    )


def link_root(site: Path, latest: str) -> int:
    """Write root redirects to every page of ``latest`` and copy its assets.

    Returns the number of redirects written.
    """
    version_root = site / latest
    count = 0
    for page in sorted(version_root.rglob("*.html")):
        relative = page.relative_to(version_root)
        stub = site / relative
        if relative.as_posix() == "404.html":
            # Served at any missing address, so only an absolute link works from it.
            stub.write_text(redirect_page(f"{urlsplit(SITE_URL).path}{latest}/"), encoding="utf-8")
            count += 1
            continue
        if stub.exists():
            continue
        stub.parent.mkdir(parents=True, exist_ok=True)
        target_dir = os.path.relpath(page.parent, stub.parent).replace(os.sep, "/")
        target = f"{target_dir}/" if page.name == "index.html" else f"{target_dir}/{page.name}"
        stub.write_text(redirect_page(target.removeprefix("./")), encoding="utf-8")
        count += 1
    assets = version_root / "assets"
    if assets.is_dir():
        shutil.copytree(assets, site / "assets", dirs_exist_ok=True)
    return count


def write_versions(site: Path, labels: list[str]) -> None:
    """Write ``versions.json`` in the form the theme's version menu reads."""
    newest = labels[0]
    versions = [
        {"version": label, "title": label, "aliases": ["latest"] if label == newest else []}
        for label in labels
    ]
    (site / "versions.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Build every version into ``--out``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("site"))
    parser.add_argument(
        "--head",
        metavar="LABEL",
        help="Also build the working tree as version LABEL, replacing a tag of that label.",
    )
    args = parser.parse_args()
    root = Path.cwd()
    site: Path = args.out.resolve()
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    tags = release_tags(root)
    labels = sorted({*tags, *([args.head] if args.head else [])}, key=_label_key, reverse=True)
    if not labels:
        raise SystemExit("no release tags and no --head; nothing to build")
    with tempfile.TemporaryDirectory() as scratch:
        for label in labels:
            target = site / label
            env = Path(scratch) / f"env-{label}"
            if label == args.head:
                build_version(root, label, target, env)
                continue
            worktree = Path(scratch) / f"tree-{label}"
            _run("git", "worktree", "add", "--detach", str(worktree), tags[label], cwd=root)
            try:
                build_version(worktree, label, target, env)
            finally:
                _run("git", "worktree", "remove", "--force", str(worktree), cwd=root)
    shutil.copytree(site / labels[0], site / "latest")
    write_versions(site, labels)
    redirects = link_root(site, "latest")
    print(f"built {', '.join(labels)} into {site}; {redirects} root redirects")


if __name__ == "__main__":
    main()

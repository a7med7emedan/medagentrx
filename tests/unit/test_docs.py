# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""README and documentation: links resolve, images have text, generated pages are current."""

import importlib
import re
import sys
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

PAGES = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)")
SRC = re.compile(r'(?:src|href)="([^"]+)"')


def _targets(page: Path) -> list[str]:
    text = page.read_text(encoding="utf-8")
    return LINK.findall(text) + SRC.findall(text)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_relative_links_resolve(page: Path) -> None:
    for target in _targets(page):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        assert (page.parent / path).exists(), f"{page.name}: broken link {target}"


def test_readme_images_have_alt_text() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    images = re.findall(r"<img [^>]*>", text)
    assert len(images) >= 8
    for tag in images:
        alt = re.search(r'alt="([^"]*)"', tag)
        assert alt is not None, tag
        assert alt.group(1).strip(), tag


def test_readme_follows_the_planned_order() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    order = [
        "logo.svg",
        "badge",
        "retrained by scheduled pipelines and by AI agents",
        "how-it-works.svg",
        "## What it checks",
        "## Quick start",
        "## The plan",
        "## Automated retraining and agents",
        "## Continuous integration",
        "## Verdicts",
        "## Validation",
        "## Security",
        "## Citing",
        "## Disclaimer",
        "## Author",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_generated_pages_are_current() -> None:
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    make_docs = importlib.import_module("make_docs")
    assert (REPO_ROOT / "docs" / "plan-reference.md").read_text(
        encoding="utf-8"
    ) == make_docs.plan_reference()
    assert (REPO_ROOT / "docs" / "checks.md").read_text(encoding="utf-8") == make_docs.checks_page()
    assert (REPO_ROOT / "docs" / "cli-reference.md").read_text(
        encoding="utf-8"
    ) == make_docs.cli_reference()
    assert (REPO_ROOT / "docs" / "api.md").read_text(encoding="utf-8") == make_docs.api_reference()


def test_cli_reference_covers_every_command() -> None:
    import typer

    from medagentrx.cli import app

    page = (REPO_ROOT / "docs" / "cli-reference.md").read_text(encoding="utf-8")
    root = typer.main.get_command(app)
    for name, command in root.commands.items():  # type: ignore[attr-defined]
        subcommands = getattr(command, "commands", None) or {"": command}
        for sub in subcommands:
            title = " ".join(part for part in ("## medagentrx", name, sub) if part)
            assert title in page, title


def test_every_docs_page_is_in_the_navigation() -> None:
    nav = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    for page in sorted((REPO_ROOT / "docs").glob("*.md")):
        if (
            page.name
            in {
                "fingerprint.md",
                "ledger.md",
                "agents.md",
                "methods.md",
                "tutorial.md",
                "glossary.md",
                "cli-reference.md",
                "api.md",
            }
            or page.name in nav
        ):
            assert page.name in nav, page.name

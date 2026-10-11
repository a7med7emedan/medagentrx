# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""A small document model rendered to Markdown and to self-contained HTML.

The plan document and the model card are built once as sections of
paragraphs, lists and tables, then written in either format. HTML output is
escaped throughout and loads nothing.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Para:
    """A paragraph of plain text."""

    text: str


@dataclass(frozen=True)
class Bullets:
    """A bulleted list. Items may be text or nested lists after a text item."""

    items: Sequence[str | Bullets]


@dataclass(frozen=True)
class Table:
    """A table with a header row."""

    headers: Sequence[str]
    rows: Sequence[Sequence[str]]


Block = Para | Bullets | Table


@dataclass
class Section:
    """A titled section with blocks and subsections."""

    title: str
    blocks: list[Block] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


@dataclass
class Document:
    """A titled document."""

    title: str
    intro: list[Block]
    sections: list[Section]
    footer: str


# Markdown ------------------------------------------------------------------------------


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _md_bullets(bullets: Bullets, depth: int = 0) -> list[str]:
    lines = []
    for item in bullets.items:
        if isinstance(item, Bullets):
            lines += _md_bullets(item, depth + 1)
        else:
            lines.append(f"{'  ' * depth}- {item}")
    return lines


def _md_block(block: Block) -> list[str]:
    if isinstance(block, Para):
        return [block.text, ""]
    if isinstance(block, Bullets):
        return [*_md_bullets(block), ""]
    lines = [
        "| " + " | ".join(_md_cell(h) for h in block.headers) + " |",
        "|" + "---|" * len(block.headers),
    ]
    lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in block.rows]
    return [*lines, ""]


def _md_section(section: Section, level: int) -> list[str]:
    lines = [f"{'#' * level} {section.title}", ""]
    for block in section.blocks:
        lines += _md_block(block)
    for child in section.sections:
        lines += _md_section(child, level + 1)
    return lines


def to_markdown(document: Document) -> str:
    """Render as Markdown."""
    lines = [f"# {document.title}", ""]
    for block in document.intro:
        lines += _md_block(block)
    for section in document.sections:
        lines += _md_section(section, 2)
    lines += ["---", "", document.footer, ""]
    return "\n".join(lines)


# HTML ----------------------------------------------------------------------------------

_STYLE = """
body { margin: 0; font: 15px/1.55 system-ui, -apple-system, sans-serif; color: #1E293B; }
main { max-width: 900px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.5rem; }
h2 { font-size: 1.2rem; margin-top: 32px; border-bottom: 1px solid #E2E8F0; }
h3 { font-size: 1.05rem; } h4 { font-size: 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; margin: 8px 0 16px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #E2E8F0; }
th { background: #F1F5F9; }
footer { margin-top: 40px; font-size: .85rem; color: #475569; border-top: 1px solid #E2E8F0; }
"""


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _html_bullets(bullets: Bullets) -> str:
    parts: list[str] = []
    for item in bullets.items:
        if isinstance(item, Bullets):
            if parts:
                parts[-1] = parts[-1].removesuffix("</li>") + _html_bullets(item) + "</li>"
            else:
                parts.append(f"<li>{_html_bullets(item)}</li>")
        else:
            parts.append(f"<li>{_e(item)}</li>")
    return "<ul>" + "".join(parts) + "</ul>"


def _html_block(block: Block) -> str:
    if isinstance(block, Para):
        return f"<p>{_e(block.text)}</p>"
    if isinstance(block, Bullets):
        return _html_bullets(block)
    head = "".join(f"<th>{_e(h)}</th>" for h in block.headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in block.rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _html_section(section: Section, level: int) -> str:
    tag = f"h{min(level, 6)}"
    inner = "".join(_html_block(b) for b in section.blocks)
    inner += "".join(_html_section(child, level + 1) for child in section.sections)
    return f"<section><{tag}>{_e(section.title)}</{tag}>{inner}</section>"


def to_html(document: Document) -> str:
    """Render as one self-contained HTML page."""
    body = "".join(_html_block(b) for b in document.intro)
    body += "".join(_html_section(s, 2) for s in document.sections)
    return (
        '<!DOCTYPE html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">\n"
        '<meta name="referrer" content="no-referrer">\n'
        f"<title>{_e(document.title)}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n<main>\n"
        f"<h1>{_e(document.title)}</h1>\n{body}\n"
        f"<footer><p>{_e(document.footer)}</p></footer>\n</main>\n</body>\n</html>\n"
    )

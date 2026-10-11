# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Assert that an HTML page cannot make any network request."""

import re
from html.parser import HTMLParser


class _Audit(HTMLParser):
    """Collect every tag, attribute and style block of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str]] = []
        self.styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self._in_style = tag == "style"
        self.attributes += [(tag, name, value or "") for name, value in attrs]

    def handle_endtag(self, tag: str) -> None:
        self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)


def assert_offline(html: str) -> None:
    """No request can leave the page.

    The only literal ``http`` is the ``http-equiv`` attribute of the CSP meta tag.
    """
    assert re.findall(r"https?:", html, re.I) == []
    assert [m.start() for m in re.finditer("http", html)] == [html.index("http-equiv")]
    audit = _Audit()
    audit.feed(html)
    fetching = {
        "script",
        "link",
        "iframe",
        "object",
        "embed",
        "img",
        "image",
        "video",
        "audio",
        "source",
    }
    assert not fetching & set(audit.tags)
    for tag, name, value in audit.attributes:
        assert not name.startswith("on"), (tag, name)
        assert name not in {"src", "srcset", "action", "formaction", "background"}, (tag, name)
        if name in {"href", "xlink:href"}:
            assert value.startswith("#"), (tag, name, value)
        assert re.search(r"url\((?!#)", value) is None, (tag, name, value)
    for block in audit.styles:
        assert "@import" not in block
        assert re.search(r"url\((?!#)", block) is None

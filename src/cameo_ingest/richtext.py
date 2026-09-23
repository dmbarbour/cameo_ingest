"""Cameo stores rich text (documentation, requirement text, tagged values) as HTML.

`to_text` converts it to light Markdown-ish plain text: paragraphs, line breaks,
bullets, and tables as pipe-separated rows. Non-HTML strings pass through unchanged.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "pre", "blockquote"}
_SKIP = {"head", "style", "script", "title"}


class _Conv(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.cell = 0
        self.lists: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK or tag == "tr":
            self.out.append("\n")
            if tag in ("ul", "ol"):
                self.lists.append(tag)
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n" + "  " * max(0, len(self.lists) - 1) + "- ")
        elif tag in ("td", "th"):
            self.out.append(" | " if self.cell else "| ")
            self.cell += 1
        elif tag == "img":
            alt = dict(attrs).get("alt")
            self.out.append(f"[image{': ' + alt if alt else ''}]")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "tr":
            if self.cell:
                self.out.append(" |")
            self.cell = 0
            self.out.append("\n")
        elif tag in _BLOCK:
            if tag in ("ul", "ol") and self.lists:
                self.lists.pop()
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def is_html(text: str) -> bool:
    t = text.lstrip()[:200].lower()
    return t.startswith(("<html", "<!doctype html", "<body", "<p>"))


def to_text(text: str | None) -> str:
    if not text:
        return ""
    if not is_html(text):
        return text.strip()
    conv = _Conv()
    try:
        conv.feed(text)
        conv.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", text).strip()
    s = "".join(conv.out)
    s = "\n".join(line.rstrip() for line in s.splitlines())
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

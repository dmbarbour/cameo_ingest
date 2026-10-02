"""An element's section, built once as data and rendered twice: as Markdown for pages, and as
plain text for chunks and LLM inputs (AR-003R2). Plain text used to be parsed back out of the
page Markdown, which corrupted model text that looked like markup (AR-003).

A section is a title, fields and blocks. Its text is made of spans: model text as it is, names
(escaped on pages), and references to elements, which pages link and plain text names.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import plain as pl
from .text import md_inline, one_line

Link = Callable[[str, str], str]  # (element id, label) -> Markdown: a link to its page, or the escaped label


@dataclass(frozen=True)
class Span:
    text: str  # as plain text shows it
    style: str = ""  # "bold", "italic" or "code" on pages
    ref: str | None = None  # an element: linked on pages where it has a page
    escape: bool = False  # a name: escaped on pages (model text is not)
    md: str | None = None  # Markdown made elsewhere (a diagram's legend line), shown as it is on pages


Line = tuple[Span, ...]


def line(*parts: str | Span) -> Line:
    """A line from spans and raw strings (model text, or text of our own)."""
    return tuple(p if isinstance(p, Span) else Span(p) for p in parts if p != "")


def name(text: str, style: str = "") -> Span:
    return Span(text, style, escape=True)


def ref(element_id: str, label: str) -> Span:
    return Span(label, ref=element_id)


def markdown_line(md: str) -> Line:
    """A line already in Markdown (a diagram legend's), with its plain text, indented as it is."""
    return (Span(md[:len(md) - len(md.lstrip())] + pl.plain(md), md=md),)


def to_markdown(spans: Line, link: Link) -> str:
    out = []
    for s in spans:
        if s.md is not None:
            out.append(s.md)
            continue
        t = link(s.ref, s.text) if s.ref is not None else md_inline(s.text) if s.escape else s.text
        out.append({"bold": f"**{t}**", "italic": f"*{t}*", "code": f"`{t}`"}.get(s.style, t))
    return "".join(out)


def to_plain(spans: Line) -> str:
    return "".join(s.text for s in spans)


@dataclass
class Block:
    """A block of a section, under a label: "**Documentation:**" on pages, "Documentation:" in
    plain text (`name`)."""

    name: str
    lines: list[Line]
    label: str = ""  # the page's label line, when it isn't "**{name}:**"
    form: str = "text"  # "text": label, blank line, lines; "list": label, lines; "inline": label and lines on one line
    detail: bool = False  # structure (members, tagged values), which plain chunks put after the meaning
    quoted: bool = False  # quoted on pages (requirement text)
    fenced: bool = False  # a code block on pages (a specification)
    before: list[str] = field(default_factory=list)  # Markdown lines before the label (an annotation's image)

    def markdown(self, link: Link) -> list[str]:
        out = self.before[:]
        if not self.lines:
            return out
        label = self.label or f"**{self.name}:**"
        body = [to_markdown(ln, link) for ln in self.lines]
        if self.form == "inline":
            return out + [f"{label} {', '.join(body)}", ""]
        if self.quoted:
            body = ["> " + "\n".join(body).replace("\n", "\n> ")]
        if self.fenced:
            body = ["```", *body, "```"]
        return out + ([label, "", *body, ""] if self.form == "text" else [label, *body, ""])

    def plain(self) -> str:
        sep = ", " if self.form == "inline" else "\n"
        return re.sub(r"\n{3,}", "\n\n", sep.join(to_plain(ln) for ln in self.lines)).strip()


@dataclass
class Section:
    title: Line
    fields: list[tuple[str, Line]]
    blocks: list[Block]

    def markdown(self, level: int, link: Link) -> list[str]:
        """The section's Markdown lines, without its trace line, which callers place."""
        out = [f"{'#' * level} {to_markdown(self.title, link)}", ""]
        out += [f"- **{k}:** {to_markdown(v, link)}" for k, v in self.fields]
        out.append("")
        for b in self.blocks:
            out += b.markdown(link)
        return out

    def plain(self, heading: str) -> tuple[list[str], list[str]]:
        """Plain parts under `heading`: (meaning, details). The meaning holds the fields (but its
        kind and qualified name, which the heading says), then the blocks of meaning; the details
        hold members and tagged values: together when they fit in one part, apart otherwise
        (plan RE-08)."""
        meaning = [f"{k}: {to_plain(v)}" for k, v in self.fields if k not in ("Kind", "Qualified name")]
        detail: list[str] = []
        for b in self.blocks:
            text = b.plain()
            if not text:
                continue
            inline = "\n" not in text and len(text) < 200 and not text.startswith("- ")  # lists keep their lines
            (detail if b.detail else meaning).append(f"{b.name}: {one_line(text)}" if inline else f"{b.name}:\n{text}")
        together = "\n".join(meaning + detail)
        if pl.tokens(heading) + pl.tokens(together) + 8 <= pl.BUDGET:
            return pl.parts(heading, together), []
        # Always a meaning chunk: the heading alone (name, kind, place, project) is what a lookup finds.
        return (pl.parts(heading, "\n".join(meaning)),
                pl.parts(f"{heading}, details", "\n".join(detail)) if detail else [])

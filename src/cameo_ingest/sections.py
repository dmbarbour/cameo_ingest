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


def cut(spans: Line, limit: int) -> Line:
    """The line cut at `limit` characters of text, with an ellipsis."""
    out: list[Span] = []
    room = limit
    for s in spans:
        if len(s.text) <= room:
            out.append(s)
            room -= len(s.text)
            continue
        out.append(Span(s.text[:room].rstrip() + "…", s.style, s.ref, s.escape))
        break
    return tuple(out)


PAGE_CELL = 500  # characters of a table's cell on a page (plan CT); its CSV has them whole
CHUNK_CELL = 300  # in a chunk: the row's element has its own chunk


@dataclass
class Block:
    """A block of a section, under a label: "**Documentation:**" on pages, "Documentation:" in
    plain text (`name`)."""

    name: str
    lines: list[Line]
    label: str = ""  # the page's label line, when it isn't "**{name}:**"
    form: str = "text"  # "text": label, blank line, lines; "list": label, lines; "inline": label and lines on one line;
    # "table": label, then `columns` and `rows` as a table on pages, a line per row in plain text
    detail: bool = False  # structure (members, tagged values), which plain chunks put after the meaning
    quoted: bool = False  # quoted on pages (requirement text)
    fenced: bool = False  # a code block on pages (a specification)
    before: list[str] = field(default_factory=list)  # Markdown lines before the label (an annotation's image)
    columns: list[str] = field(default_factory=list)  # a table's headers
    rows: list[list[Line]] = field(default_factory=list)  # a table's cells, by row

    def markdown(self, link: Link) -> list[str]:
        out = self.before[:]
        if self.form == "table":
            if not self.rows:
                return out
            esc = lambda t: t.replace("|", "\\|").replace("\n", " ")
            head = ["| " + " | ".join(esc(md_inline(c)) for c in self.columns) + " |", "|" + "---|" * len(self.columns)]
            body = ["| " + " | ".join(esc(to_markdown(cut(c, PAGE_CELL), link)) for c in row) + " |" for row in self.rows]
            return out + [self.label or f"**{self.name}:**", "", *head, *body, ""]
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
        if self.form == "table":  # every cell named, so that a chunk cut between rows still says what it is
            lines = []
            for row in self.rows:
                cells = [(h, one_line(to_plain(cut(c, CHUNK_CELL)))) for h, c in zip(self.columns, row, strict=True)]
                number = cells[0][1] + ". " if cells and cells[0][0] == "#" else ""
                lines.append("- " + number + "; ".join(f"{h}: {t}" for h, t in cells if t and h != "#"))
            return "\n".join(lines)
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

    def _blocks(self) -> tuple[list[str], list[str]]:
        """The blocks as plain text: (meaning, details), each a block's lines under its name."""
        meaning: list[str] = []
        detail: list[str] = []
        for b in self.blocks:
            text = b.plain()
            if not text:
                continue
            inline = "\n" not in text and len(text) < 200 and not text.startswith("- ")  # lists keep their lines
            (detail if b.detail else meaning).append(f"{b.name}: {one_line(text)}" if inline else f"{b.name}:\n{text}")
        return meaning, detail

    def text(self) -> str:
        """The whole section as plain text, in one piece, for LLM inputs (AR-018): its title, every
        field, then its blocks, meaning before details."""
        meaning, detail = self._blocks()
        return "\n".join([to_plain(self.title), *(f"{k}: {to_plain(v)}" for k, v in self.fields), *meaning, *detail])

    def plain(self, heading: str) -> tuple[list[str], list[str]]:
        """Plain parts under `heading`: (meaning, details). The meaning holds the fields (but its
        kind and qualified name, which the heading says), then the blocks of meaning; the details
        hold members and tagged values: together when they fit in one part, apart otherwise
        (plan RE-08)."""
        blocks, detail = self._blocks()
        meaning = [f"{k}: {to_plain(v)}" for k, v in self.fields if k not in ("Kind", "Qualified name")] + blocks
        together = "\n".join(meaning + detail)
        if pl.tokens(heading) + pl.tokens(together) + 8 <= pl.BUDGET:
            return pl.parts(heading, together), []
        # Always a meaning chunk: the heading alone (name, kind, place, project) is what a lookup finds.
        return (pl.parts(heading, "\n".join(meaning)),
                pl.parts(f"{heading}, details", "\n".join(detail)) if detail else [])

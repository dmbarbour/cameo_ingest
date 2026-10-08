"""Small text helpers shared by the writers."""

from __future__ import annotations

import json
import re
from typing import Any

VALUE_CHARS = 4000  # a tagged value shown on a page: longer ones are data or configuration (FU-020)
_HEX = re.compile(r"(?:[0-9a-fA-F]{1,2}\s+){16}")
# What some bytes are, by how they start: a name, and the media type of an image a vision model reads.
_MAGIC = ((b"<?xml", "XML", None), (b"<svg", "SVG image", None), (b"\x89PNG", "PNG image", "image/png"),
          (b"\xff\xd8\xff", "JPEG image", "image/jpeg"), (b"GIF8", "GIF image", "image/gif"),
          (b"PK\x03\x04", "zip archive", None))


def image_mime(head: bytes) -> str | None:
    """The media type of an embedded image (PNG, JPEG or GIF), from its first bytes."""
    return next((mime for magic, _, mime in _MAGIC if mime and head.startswith(magic)), None)


def shown_value(value: str, limit: int = VALUE_CHARS) -> str:
    """A tagged value as a page shows it: hex-encoded bytes (such as the images of
    «CustomImageHolder») described rather than shown, and other long values cut (FU-020)."""
    if len(value) > limit and _HEX.match(value) and re.fullmatch(r"[0-9a-fA-F\s]+", value):
        head = bytes.fromhex("".join(f"{b:0>2}" for b in value[:2000].split()[:512]))
        kind = next((k for magic, k, _ in _MAGIC if head.lstrip().startswith(magic)), "binary data")
        if kind == "XML" and b"<svg" in head:
            kind = "SVG image"
        return f"({kind}, {len(value.split()):,} bytes, hex-encoded; not shown)"
    if len(value) > limit:
        return f"{value[:limit]}… (cut; {len(value):,} characters in all)"
    return value


# Characters that XML 1.0 forbids, which an .xlsx cell or an SVG can't hold: model text has been
# seen with vertical tabs and other control characters.
XML_FORBIDDEN = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def xml_safe(text: str) -> str:
    return XML_FORBIDDEN.sub("", text)


def one_line(text: str) -> str:
    """Names, notes and values may span lines; a legend, sketch or digest gives each on one."""
    return " ".join(text.split())


def clip(text: str, limit: int) -> str:
    """`text` on one line, at most `limit` characters: cut after a whole word, with "…" (CQ-018)."""
    text = one_line(text)
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip() + "…"


SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def first_sentence(text: str, limit: int) -> str:
    """The first sentence of `text`, on one line, clipped to `limit`."""
    text = one_line(text)
    m = SENTENCE_END.search(text)
    return clip(text[:m.start()] if m else text, limit)


# Where a reply cut short can end: after a sentence (a stop not after a bare number, as a list's
# "2." is), or at a line's end (a list item, a heading).
_WHOLE = re.compile(r"(?<![\s\d])[.!?][\"'\u201d)\]]*(?=\s|$)|\n")


def whole_sentences(text: str) -> str:
    """`text` as far as its last whole sentence or line: what a reply cut short says for certain
    (RN-002); empty when it has none."""
    ends = [m.end() for m in _WHOLE.finditer(text)]
    return text[:ends[-1]].rstrip() if ends else ""


def natural_key(text: str) -> list[tuple[int, int | str]]:
    """A sort key that orders numbers in text as numbers: REQ-2 before REQ-10, REQ.1.2 before REQ.1.10."""
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.split(r"(\d+)", text) if t]


def plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}{'' if n == 1 else 's'}"


def slug(text: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return (s or "unnamed")[:maxlen]


def front_matter(meta: dict[str, Any]) -> str:
    # JSON values are valid YAML 1.2, which keeps this dependency-free and unambiguous.
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)


def tidy(text: str) -> str:
    """Model text as it goes on a page: line ends normalized, outer white space stripped. It is
    not escaped; the plain chunks remove only the markup emit writes (AR-003)."""
    return text.replace("\r\n", "\n").strip()


# Characters that change the meaning of an inline name: links ([ ]), emphasis (*), code
# spans (`), HTML tags (<) and the escape character itself. Intraword `_` is safe in
# CommonMark and very common in model names, so it is left alone to keep chunk text clean.
_MD_SPECIAL = re.compile(r"([\\`*\[\]<])")
_MD_ESCAPED = re.compile(r"\\([\\`*\[\]<])")


def md_inline(text: str) -> str:
    """Escape a model name or label for use inside a Markdown line."""
    return _MD_SPECIAL.sub(r"\\\1", text)


def md_plain(text: str) -> str:
    """Undo `md_inline`, for plain-text chunk bodies."""
    return _MD_ESCAPED.sub(r"\1", text)


# The one pattern for a Markdown link (AR-023): its label may hold the brackets md_inline escapes.
LINK = re.compile(r"\[((?:[^\[\]\\]|\\.)*)\]\([^)]*\)")
TRACE = re.compile(r"<sub>trace: `[^`]*`</sub>")


def strip_links(text: str) -> str:
    """Markdown links reduced to their labels."""
    return LINK.sub(r"\1", text)


def flat(text: str) -> str:
    """Text for matching phrases in: lower case, links reduced to their labels, without trace
    lines, Markdown's code and bold marks or escapes, spaces collapsed, so that
    `**headLossLimit** = `2.4`` holds "headLossLimit = 2.4"."""
    text = strip_links(TRACE.sub("", text))
    return " ".join(re.sub(r"[`*\\]", "", text.lower()).split())


DOORS_ID = re.compile(r"^\s*(?:[-–•*]\s+)?\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\]\s*")  # "[REQ-1-OAD-0468] ...", "- [REQ-...] ...": a DOORS id starting a text


def requirement_title(name: str | None, rid: str | None, text: str | None) -> str:
    """A requirement's readable title: its name with its id; or, unnamed (as DOORS imports are),
    its id and the start of its text."""
    text = one_line(text or "")
    m = DOORS_ID.match(text)
    if m:  # the id in the text is the one people use; the Id tag is often a database number
        rid, text = m.group(1), text[m.end():]
    if name:
        return f"{name} ({rid})" if rid else name
    start = text if len(text) <= 90 else text[:89].rsplit(" ", 1)[0] + "…"
    return f"{rid}: {start}" if rid and start else rid or start or "(unnamed)"

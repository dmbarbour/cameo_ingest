"""Small text helpers shared by the writers."""

from __future__ import annotations

import json
import re
from typing import Any

VALUE_CHARS = 4000  # a tagged value shown on a page: longer ones are data or configuration (FU-020)
_HEX = re.compile(r"(?:[0-9a-fA-F]{1,2}\s+){16}")
_MAGIC = ((b"<?xml", "XML"), (b"<svg", "SVG image"), (b"\x89PNG", "PNG image"), (b"\xff\xd8\xff", "JPEG image"),
          (b"GIF8", "GIF image"), (b"PK\x03\x04", "zip archive"))


def shown_value(value: str, limit: int = VALUE_CHARS) -> str:
    """A tagged value as a page shows it: hex-encoded bytes (such as the images of
    «CustomImageHolder») described rather than shown, and other long values cut (FU-020)."""
    if len(value) > limit and _HEX.match(value) and re.fullmatch(r"[0-9a-fA-F\s]+", value):
        head = bytes.fromhex("".join(f"{b:0>2}" for b in value[:2000].split()[:512]))
        kind = next((k for magic, k in _MAGIC if head.lstrip().startswith(magic)), "binary data")
        if kind == "XML" and b"<svg" in head:
            kind = "SVG image"
        return f"({kind}, {len(value.split()):,} bytes, hex-encoded; not shown)"
    if len(value) > limit:
        return f"{value[:limit]}… (cut; {len(value):,} characters in all)"
    return value


def plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}{'' if n == 1 else 's'}"


def slug(text: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return (s or "unnamed")[:maxlen]


def front_matter(meta: dict[str, Any]) -> str:
    # JSON values are valid YAML 1.2, which keeps this dependency-free and unambiguous.
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)


def md_escape(text: str) -> str:
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

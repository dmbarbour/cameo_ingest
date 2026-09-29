"""Small text helpers shared by the writers."""

from __future__ import annotations

import json
import re
from typing import Any


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

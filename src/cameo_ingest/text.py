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

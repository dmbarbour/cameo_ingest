"""Provenance records attached to every emitted file, row and chunk.

A trace answers "where did this text come from?" down to the model element:

    content (the sha256 of a Cameo project's own bytes: its token, `sha256:<hex>`)
      -> archive entry (e.g. com.nomagic.magicdraw.uml_model.model)
        -> xmi:id + line number
          -> derivation (deterministic extraction, or LLM model + prompt hash)

`Trace.locator()` flattens this into one string suitable for a CSV column. Where the
content was found (input files, archive chains, --meta values) is not part of a trace:
it is recorded per token in state.sqlite and exported to provenance.jsonl, so a
project's output never changes because the content turned up somewhere else.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from . import __version__

TOOL = f"cameo-ingest/{__version__}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ContentInfo:
    """What a project's output is about: the content's hash and the file name under
    which it was first seen."""

    sha256: str
    name: str

    @property
    def token(self) -> str:
        """The stable reference to this content's provenance."""
        return f"sha256:{self.sha256}"


@dataclass(frozen=True)
class Derivation:
    method: str = "extracted"  # "extracted" | "rendered" | "llm"
    tool: str = TOOL
    model: str | None = None
    prompt_sha256: str | None = None
    template: str | None = None  # the prompt template and version, e.g. "package-summary@v1"
    inputs: tuple[str, ...] = ()  # locators of the inputs an LLM saw


EXTRACTED = Derivation()


@dataclass(frozen=True)
class Trace:
    content_sha256: str
    entry: str | None = None  # archive entry of the project
    xmi_id: str | None = None
    line: int | None = None
    qualified_name: str | None = None
    derivation: Derivation = EXTRACTED

    def locator(self) -> str:
        loc = f"sha256:{self.content_sha256[:16]}"
        if self.entry:
            loc += f"!{self.entry}"
        if self.xmi_id:
            loc += f"#{self.xmi_id}"
        if self.line:
            loc += f"@L{self.line}"
        return loc

    def with_(self, **kw: Any) -> Trace:
        d = {**self.__dict__, **kw}
        return Trace(**d)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["derivation"]["inputs"] = list(self.derivation.inputs)
        d["locator"] = self.locator()
        return {k: v for k, v in d.items() if v not in (None, [], ())}

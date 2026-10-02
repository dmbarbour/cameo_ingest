"""A project's chunks, as they are made: section chunks, running text, generated text, in parts
that fit an embedding window (plan RA-13, AR-007R1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import chunks
from . import plain as pl
from . import sections as sx
from .annotations import Annotation
from .model import Element
from .provenance import Trace, generated_by

if TYPE_CHECKING:
    from .view import ProjectView


class ChunkSink:
    def __init__(self, view: ProjectView):
        self.view = view
        self.chunks: list[dict[str, Any]] = []  # written to index/chunks.jsonl
        self.main: dict[str, str] = {}  # element id -> its main chunk (its meaning, not its details)

    def chunk(self, *, kind: str, title: str, text: str, file: str, el: Element | None,
              trace: Trace, extra: dict[str, Any] | None = None, salt: str = "") -> None:
        if kind.startswith("generated:"):  # what it is about, and the pieces of one answer (AR-012R2)
            extra = {**(extra or {}), "annotation": chunks.chunk_id(self.view.content.sha256, kind,
                                                                    el.id if el else file, salt),
                     "primary_chunk": self.main.get(el.id) if el else None}
        if kind.startswith("generated:") and pl.tokens(text) > pl.BUDGET:
            # Generated text too long for one embedding window: in parts, each under its heading.
            first, _, rest = text.partition("\n")
            pieces = pl.parts(first, rest.strip())
            for k, piece in enumerate(pieces, 1):
                self._chunk(kind, title, piece, file, el, trace, {**(extra or {}), "piece": k, "pieces": len(pieces)},
                            f"{salt}#{k}")
            return
        self._chunk(kind, title, text, file, el, trace, extra, salt)

    def _chunk(self, kind: str, title: str, text: str, file: str, el: Element | None, trace: Trace,
               extra: dict[str, Any] | None, salt: str) -> None:
        self.chunks.append(chunks.make((self.view.content.sha256, kind, el.id if el else file, salt), title, text, {
            "kind": kind,
            "file": file,
            "project": self.view.content.name,
            "content": self.view.content.token,
            "element_id": el.id if el else None,
            "element_type": el.type if el else None,
            "qualified_name": self.view.ix.qualified_name(el.id) if el else None,
            "stereotypes": self.view.ix.stereotype_names(el.id) if el else [],
            "provenance": trace.to_dict(),
            **(extra or {}),
        }))
        if el is not None and kind in ("element", "requirement", "package", "diagram") and el.id not in self.main:
            self.main[el.id] = self.chunks[-1]["id"]

    def section_chunks(self, kind: str, el: Element, view: sx.Section, file: str, trace: Trace,
                       heading: str | None = None, extra: dict[str, Any] | None = None) -> None:
        """An element's (or package's, or diagram's) chunks: its meaning and its details, as plain
        parts under its heading (plan RE-08)."""
        title = (extra or {}).pop("title", None) or f"{el.kind} {self.view.ix.qualified_name(el.id)}"
        meaning, details = view.plain(heading or self.view.heading(el))
        for suffix, texts in (("", meaning), (":details", details)):
            for k, text in enumerate(texts, 1):
                more = {"part": k, "parts": len(texts)} if len(texts) > 1 else {}
                self.chunk(kind=kind + suffix, title=title + (", details" if suffix else ""), text=text, file=file,
                           el=el, trace=trace, extra={**(extra or {}), **more}, salt=f"{suffix}#{k}")

    def text_chunks(self, *, kind: str, title: str, text: str, file: str, el: Element | None, trace: Trace,
                    extra: dict[str, Any] | None = None, salt: str = "") -> None:
        """A chunk of running text (the project overview): plain, in parts under its first line."""
        first, _, rest = pl.plain(text).partition("\n")
        texts = pl.parts(first, rest.strip())
        for k, part in enumerate(texts, 1):
            more = {"part": k, "parts": len(texts)} if len(texts) > 1 else {}
            self.chunk(kind=kind, title=title, text=part, file=file, el=el, trace=trace,
                       extra={**(extra or {}), **more}, salt=f"{salt}#{k}")

    def generated_heading(self, a: Annotation, el: Element, kind_word: str | None = None, what: str = "",
                          names: list[str] = (), names_word: str = "covering") -> str:
        """A generated chunk's heading (AR-004R1): what it is, of which element, as its plain
        heading says it (the project included), then the names it covers as far as room allows,
        and its origin. A heading takes at most a quarter of a part (AR-004R2)."""
        head = f"{a.label} of {self.view.heading(el, kind_word)}" + (f", {what}" if what else "")
        origin = f" ({generated_by(a.trace.derivation)})"
        room = pl.HEADING - pl.tokens(head) - pl.tokens(origin) - 2
        if names and room > 8:
            head += ", " + pl.cap(f"{names_word} " + "; ".join(names), room)
        return head + origin

    def generated_chunks(self, el: Element, file: str, kind_word: str | None = None) -> None:
        """One chunk per LLM-derived annotation, with the LLM derivation as provenance."""
        for i, a in enumerate(self.view.ann.get(el.id, [])):
            if a.trace.derivation.method != "llm" or not a.text or a.module is not None or a.parts is not None:
                continue
            what = f"{el.kind} {self.view.ix.qualified_name(el.id)}"
            text = f"{self.generated_heading(a, el, kind_word)}\n\n{a.text}"
            self.chunk(kind=a.kind.chunk if a.kind else "generated:annotation", title=f"{a.label}: {what}",
                       text=text, file=file, el=el, trace=a.trace, salt=str(i))

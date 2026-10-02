"""Grading by construction (plan RE-05; review AR-005): which windows answer a question, and
which parts of its answer each holds. Each question has one rule:

- **source** (a written question): its source chunk's windows; 2 for the one with the quote, 1
  for the others. In a corpus without that chunk (another chunk style), the source element's
  chunks stand in.
- **parts** (an answer in parts: one per model, or per element along a derivation): a window
  holding any part's phrase answers, and coverage counts the parts the top windows hold.
- **fact** (a fictional project's, KOIS included since AR-005R3): a window of the project, or
  an index entry, that holds the fact answers; the other windows of answering or related
  elements relate.
- **element** (structural questions about the samples): any window of an answering element
  answers, as does a window of the project that holds the planted fact (a ledger quoting it,
  say); a related element's window relates.

A question's source states its rule (`"rule"`); question files written before that are read by
what they hold (`Question.of`). Windows are anything with `id`, `text`, `element_id` and `kind`
(`harness.Unit`); `Corpus` flattens their text once for every question.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..text import flat

RULES = ("source", "parts", "fact", "element")


def normal(text: str) -> str:
    """Letters and digits only, in lower case: a written question's quote and a window compared
    whatever their markup."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


Evidence = str | Iterable[str | Iterable[str]]  # a phrase, or alternatives: phrases, or lists of phrases


def holds(evidence: Evidence, text: str) -> bool:
    """Whether `text` holds the evidence, whatever its case and markup: one of its alternatives,
    each a phrase or a list of phrases that must all be there (a thread holds a derivation as
    "what derives from X" in its heading and the derived requirement on a line)."""
    return _held(_phrases(evidence), flat(text))


class Window(Protocol):
    id: str  # a chunk id, or a chunk id + "#w<n>"
    text: str
    element_id: str | None
    kind: str


class Corpus:
    """The windows questions are graded against, with each text flattened once."""

    def __init__(self, windows: Sequence[Window]):
        self.windows = windows
        self.flat = [flat(w.text) for w in windows]
        self.chunk = [w.id.split("#w")[0] for w in windows]
        self._normal: list[str] | None = None

    def normal(self, i: int) -> str:
        if self._normal is None:
            self._normal = [normal(f) for f in self.flat]
        return self._normal[i]


Phrases = tuple[tuple[str, ...], ...]  # alternatives, each phrases that must all be there, flattened


def _phrases(evidence: Evidence) -> Phrases:
    alts = [evidence] if isinstance(evidence, str) else evidence
    return tuple(t for t in (tuple(flat(p) for p in ([a] if isinstance(a, str) else a) if p) for a in alts) if t)


def _held(phrases: Phrases, flat_text: str) -> bool:
    return any(all(p in flat_text for p in alt) for alt in phrases)


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    rule: str
    answers: frozenset[str] = frozenset()  # element ids
    related: frozenset[str] = frozenset()
    evidence: Phrases = ()
    by_element: Mapping[str, Phrases] = field(default_factory=dict)  # where each element says it its way
    groups: tuple[Phrases, ...] = ()  # the parts of an answer in parts
    prefix: str = ""  # the project's element ids start so
    quote: str = ""  # normalized
    sources: frozenset[str] = frozenset()  # a written question's source chunks
    source_element: str | None = None

    @classmethod
    def of(cls, d: Mapping[str, Any]) -> Question:
        """A question as its source writes it (a dict, as in a questions file)."""
        rule = d.get("rule") or ("source" if d.get("answer_chunks") else "parts" if d.get("evidence_groups")
                                 else "fact" if d.get("prefix") else "element")
        q = cls(id=d["id"], question=d["question"], rule=rule,
                answers=frozenset(d.get("answers", ())), related=frozenset(d.get("related", ())),
                evidence=_phrases(d.get("evidence", ())),
                by_element={e: _phrases(v) for e, v in (d.get("evidence_by_element") or {}).items()},
                groups=tuple(_phrases(g) for g in d.get("evidence_groups", ())),
                prefix=d.get("prefix", ""), quote=normal(d.get("quote", "")),
                sources=frozenset(d.get("answer_chunks", ())), source_element=d.get("source_element"))
        problem = {"source": not q.sources, "parts": not q.groups or not all(q.groups),
                   "fact": not q.prefix or not (q.evidence or q.by_element),
                   "element": not q.answers}.get(rule, True)
        if problem:
            raise ValueError(f"question {q.id}: rule {rule!r} " + ("unknown" if rule not in RULES else
                                                                   "lacks what it grades by"))
        return q

    def grades(self, c: Corpus, judged: Mapping[str, int] | None = None) -> dict[int, int]:
        """Window index -> grade (2 answers, 1 relates), overridden by the judge panel's grades
        where it judged (`judged`: window id -> grade)."""
        out: dict[int, int] = {}
        if self.rule == "source":
            sources = self.sources
            if not any(ch in sources for ch in c.chunk):
                sources = frozenset(ch for ch, w in zip(c.chunk, c.windows, strict=True)
                                    if w.element_id and w.element_id == self.source_element)
            for i, ch in enumerate(c.chunk):
                if ch in sources:
                    out[i] = 2 if self.quote and self.quote in c.normal(i) else 1
        elif self.rule == "parts":
            for i, f in enumerate(c.flat):
                if any(_held(g, f) for g in self.groups):
                    out[i] = 2
        else:
            for i, (w, f) in enumerate(zip(c.windows, c.flat, strict=True)):
                e = w.element_id or ""
                own = bool(self.prefix) and e.startswith(self.prefix)
                if self.rule == "fact":
                    # An index entry spans projects; the fictional phrases occur nowhere else.
                    if (own or w.kind == "index:id") and (
                            _held(self.evidence, f) or _held(self.by_element.get(e, ()), f)):
                        out[i] = 2
                    elif e in self.answers or e in self.related:
                        out[i] = 1
                elif e in self.answers or (own and _held(self.evidence, f)):
                    out[i] = 2
                elif e in self.related:
                    out[i] = 1
        if judged:
            for i, w in enumerate(c.windows):
                if w.id in judged:
                    if judged[w.id]:
                        out[i] = judged[w.id]
                    else:
                        out.pop(i, None)
        return out

    def covers(self, c: Corpus, grades: Mapping[int, int]) -> tuple[int, dict[int, frozenset[int]]]:
        """How many parts the answer has, and the parts each graded window holds: for an answer
        in parts, the groups it holds a phrase of; otherwise the one part, held by each window
        that answers."""
        if self.rule == "parts":
            return len(self.groups), {i: frozenset(k for k, g in enumerate(self.groups) if _held(g, c.flat[i]))
                                      for i in grades}
        return 1, {i: frozenset([0]) for i, v in grades.items() if v == 2}


# A question's grades, how many parts its answer has, and the parts each window holds.
Graded = tuple[dict[int, int], int, dict[int, frozenset[int]]]


def grade_all(questions: Sequence[Mapping[str, Any]], c: Corpus,
              judged: Mapping[str, Mapping[str, int]] | None = None) -> list[Graded]:
    """Each question graded once, whatever the systems that rank for it (AR-020R1). `judged`: the
    judge panel's grades, by question id and window id, which override construction."""
    out = []
    for q in questions:
        qq = Question.of(q)
        g = qq.grades(c, (judged or {}).get(q["id"]))
        out.append((g, *qq.covers(c, g)))
    return out

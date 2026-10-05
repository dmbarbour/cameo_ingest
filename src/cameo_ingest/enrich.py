"""LLM enrichment of one project (AR-008): typed requests, and their answers folded into
annotations a round at a time. The first round asks about every diagram (or each module of a
large one), embedded image and package (or each part of a large one); then large diagrams are
described as a whole from their modules' descriptions (plan DV-04), and large packages
summarized from their parts' summaries, through runs of at most MAX_SUMMARIES while there are
more (DV-05).

    enricher = Enricher(...)
    ... enricher.diagram(...), enricher.image(...), enricher.packages()
    enricher.run(progress, name, concurrency)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from . import annotations as an
from . import prompt_values as pv
from .annotations import Annotation
from .files import FilePlan
from .llm import EnrichmentSession
from .model import Element
from .partition import Partition, sequence_partition
from .progress import Progress
from .prompt_values import Level
from .prompts import CURRENT, MAX_SUMMARIES, PART_CHARS, Template, split_class
from .provenance import Derivation, Trace
from .view import ProjectView
from .vision import fit_image

log = logging.getLogger(__name__)

MIN_SECTIONS_FOR_SUMMARY = 5
INSTANCE_SHARE = 0.8  # a large package with this share of instance specifications is summarized from a digest


@dataclass
class Request:
    """One LLM request, made after rendering so that requests can run in parallel."""

    kind: an.AnnotationKind
    key: str  # the diagram, package or image entry it is about
    trace: Trace
    call: Callable[[], Any]
    module: int | None = None  # of a large diagram, or part of a large package
    parts: tuple[int, int] | None = None  # a run of a large package's parts


def answer(requests: list[Request], progress: Progress, label: str, concurrency: int) -> list[Any]:
    """Results in request order, whatever order the answers come in, so output stays
    deterministic (BASE-019R4)."""
    if not requests:
        return []
    with progress.phase(f"{label}: LLM", len(requests), "request") as ph:
        if concurrency <= 1:
            results = []
            for r in requests:
                results.append(r.call())
                ph.advance()
            return results
        pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="llm")
        try:
            futures = [pool.submit(r.call) for r in requests]
            for _ in as_completed(futures):
                ph.advance()
            return [f.result() for f in futures]  # re-raises e.g. a replay miss
        finally:  # on Ctrl-C, queued requests are dropped rather than waited for
            pool.shutdown(wait=False, cancel_futures=True)


def _ask_with_image(llm: EnrichmentSession, template: Template, values: dict[str, str], root: Path, rel: str, mime: str,
                    image_pixels: int = 0, notes: dict | None = None, **kw: Any) -> Any:
    # The image is read back from disk only when the request runs, so queued requests
    # don't hold every diagram in memory.
    data = (root / rel).read_bytes()
    notes = dict(notes or {})
    if image_pixels:  # the model sees at most image_pixels anyway: send no more (FU-012R3, FU-015)
        data, mime, scaled = fit_image(data, mime, image_pixels)
        if scaled:
            notes["scaled"] = scaled
    return llm.ask(template, values, image=data, mime=mime, image_path=rel, notes=notes, **kw)


def package_parts(view: ProjectView, sections: list[Element], texts: list[str],
                  limit: int = PART_CHARS[1]) -> list[list[int]]:
    """A large package's sections (indices), in parts of related elements: by nesting,
    relationships and order, each of PART_CHARS[0] to `limit` characters where the sections allow
    (plan DV-05)."""
    index = {e.id: i for i, e in enumerate(sections)}

    def section_of(el_id: str | None) -> int | None:
        """The section an element is in: its own, or its nearest owner's."""
        while el_id is not None and el_id not in index:
            el = view.ix.elements.get(el_id)
            el_id = el.owner if el else None
        return index.get(el_id) if el_id else None

    parents = [section_of(e.owner) for e in sections]
    links = [(a, b) for r in view.rels
             if (a := section_of(r.source)) is not None and (b := section_of(r.target)) is not None and a != b]
    return sequence_partition([len(t) + 1 for t in texts], parents, links, min(PART_CHARS[0], limit // 2), limit)


def pieces(text: str, limit: int = PART_CHARS[1]) -> list[str]:
    """A section's text in pieces of at most `limit` characters, each headed by the section's
    title (its first line) and a field line saying which piece it is ("Piece: 2 of 3"; on the
    title's line, a model took it for part of the name): cut between lines, or between words in a
    line longer than a piece. A text that fits is one piece, as it is (plan TC-01)."""
    if len(text) <= limit:
        return [text]
    title, _, rest = text.partition("\n")
    title = title[:limit // 4]
    room = limit - len(title) - len("\nPiece: 999 of 999") - 1
    bodies: list[list[str]] = [[]]
    size = 0
    for line in rest.split("\n"):
        while True:
            take = line
            if len(line) > room:
                cut = line.rfind(" ", room // 2, room)
                take = line[:cut] if cut > 0 else line[:room]
            if size and size + len(take) + 1 > room:
                bodies.append([])
                size = 0
            bodies[-1].append(take)
            size += len(take) + 1
            line = line[len(take):].lstrip(" ")
            if not line:
                break
    n = len(bodies)
    return [f"{title}\nPiece: {i} of {n}\n" + "\n".join(b) for i, b in enumerate(bodies, 1)]


def repack(part: list[Element], texts: list[str], limit: int = PART_CHARS[1]) -> list[tuple[list[Element], str]]:
    """A part's (elements, text) as requests of at most `limit` characters: as it is when it
    fits; else its sections, in order, packed into as few as fit, a section too long for one
    split into pieces (plan TC-01). Nothing is cut."""
    whole = "\n\n".join(texts)
    if len(whole) <= limit:
        return [(part, whole)]
    out: list[tuple[list[Element], str]] = []
    els: list[Element] = []
    body = ""
    for e, text in zip(part, texts, strict=True):
        for piece in pieces(text, limit):
            if body and len(body) + 2 + len(piece) > limit:
                out.append((els, body))
                els, body = [], ""
            if e not in els:
                els = [*els, e]
            body = f"{body}\n\n{piece}" if body else piece
    out.append((els, body))
    return out


def with_context(template: Template, values: dict[str, str], context: Callable[[], str]) -> dict[str, str]:
    """`values`, with the context (plan GS) when the template in use takes it."""
    if any(s.name == "CONTEXT" for s in template.slots):
        return {**values, "CONTEXT": context()}
    return values


class Enricher:
    """A project's LLM requests, and their answers as annotations (the view's, by element) and
    image descriptions (`images`, by archive entry)."""

    def __init__(self, llm: EnrichmentSession, view: ProjectView, plan: FilePlan, root: Path, image_pixels: int,
                 part_chars: int = PART_CHARS[1]):
        self.llm, self.view, self.plan, self.annotations = llm, view, plan, view.ann
        self.ix, self.content, self.root, self.image_pixels = view.ix, view.content, root, image_pixels
        self.part_chars = part_chars  # the largest input of package text (plan TC)
        self.images: dict[str, tuple[str, Derivation]] = {}
        self.truncated = 0  # LLM inputs cut short to fit the prompt
        self._first: list[Request] = []
        self._large_diagrams: list[tuple[str, Partition, Trace, str]] = []
        self._large_packages: list[tuple[str, Trace, list[list[Element]], str]] = []
        self._described: dict[tuple[str, int], str] = {}  # modules of large diagrams, parts of large packages
        self._levels: dict[str, Level] = {}
        self._steps: dict[str, list[tuple[Level, Request | None]]] = {}
        self._round = 0

    # -- the first round ------------------------------------------------------------------------
    def diagram(self, dia_id: str, tr: Trace, rel: str) -> None:
        """A diagram whose sketch is drawn at `rel`: a description, unless there is too little
        to describe (FU-010)."""
        ix, view, llm = self.ix, self.view, self.llm
        el, graph = ix.elements[dia_id], view.graph(dia_id)
        if not llm.cfg.vision_model or graph is None:
            return
        if graph.trivial():
            llm.skip(view.trace(el).locator(), "skipped_trivial",
                     f"{len(graph.nodes)} shape(s), {len(graph.links)} connection(s)")
            return
        v = pv.diagram_description(ix, graph, ix.diagrams[dia_id])
        if v.cut:
            self.truncated += 1
            llm.truncated(view.trace(el).locator(), v.cut)
        t = CURRENT["diagram-description"]
        values = with_context(t, v.values, lambda: pv.diagram_context(ix, graph, ix.diagrams[dia_id]))
        call = partial(_ask_with_image, llm, t, values, self.root, rel, "image/png",
                       project=self.content.token, inputs=(view.trace(el).locator(), tr.locator()), notes=v.notes)
        self._first.append(Request(an.DIAGRAM, dia_id, tr, call))

    def module(self, dia_id: str, part: Partition, num: int, tr: Trace, rel: str) -> None:
        """Module `num` of a large diagram, whose sketch is drawn at `rel`."""
        if not self.llm.cfg.vision_model:
            return
        ix, view = self.ix, self.view
        v = pv.module_description(ix, part, num, ix.diagrams[dia_id])
        call = partial(_ask_with_image, self.llm, CURRENT["module-description"], v.values, self.root, rel,
                       "image/png", project=self.content.token,
                       inputs=(view.trace(ix.elements[dia_id]).locator(), tr.locator()), notes=v.notes)
        self._first.append(Request(an.MODULE, dia_id, tr, call, num))

    def large_diagram(self, dia_id: str, part: Partition, tr: Trace, rel: str) -> None:
        """A large diagram, described as a whole from its modules once they are (`rel`: its overview)."""
        self._large_diagrams.append((dia_id, part, tr, rel))

    def image(self, entry: str, rel: str, mime: str, tr: Trace) -> None:
        if self.llm.cfg.vision_model:
            call = partial(_ask_with_image, self.llm, CURRENT["image-description"], pv.image_description().values,
                           self.root, rel, mime, image_pixels=self.image_pixels, project=self.content.token,
                           inputs=(tr.locator(),))
            self._first.append(Request(an.IMAGE, entry, tr, call))

    def packages(self) -> None:
        """Package summaries from the deterministic text, so the LLM only rephrases what is there.
        A large package is summarized in parts, and then from its parts' summaries (FU-005); one
        made mostly of instance specifications, from a digest of them (FU-022)."""
        ix, view, llm = self.ix, self.view, self.llm
        if not llm.cfg.text_model:
            return
        for pkg_id in self.plan.pkg_file:
            pkg = ix.elements[pkg_id]
            sections = view.sections_in(pkg)
            if len(sections) < MIN_SECTIONS_FOR_SUMMARY:
                continue
            # Plain text, without link targets or trace lines (AR-018): the prompt, and so the
            # cached answer, depends only on the model's content, not on where it was found.
            own = view.section_view(pkg, generated=False).text()
            texts = [view.section_view(e, generated=False).text() for e in sections]
            tr = view.trace(pkg)
            text = "\n\n".join([own, *texts])
            ask = partial(llm.ask, project=self.content.token, inputs=(tr.locator(),))
            context = partial(pv.package_context, ix, pkg_id)
            if len(text) <= self.part_chars:
                t = CURRENT["package-summary"]
                self._first.append(Request(an.SUMMARY, pkg_id, tr, partial(
                    ask, t, with_context(t, pv.package_summary(text).values, context))))
                continue
            if sum(e.kind == "InstanceSpecification" for e in sections) >= INSTANCE_SHARE * len(sections):
                v = pv.instances_summary(ix, ix.qualified_name(pkg_id), own, sections, texts, self.part_chars)
                t = CURRENT["instances-summary"]
                self._first.append(Request(an.SUMMARY, pkg_id, tr, partial(
                    ask, t, with_context(t, v.values, context), notes=v.notes)))
                continue
            requests = [r for g in package_parts(view, sections, texts, self.part_chars)
                        for r in repack([sections[i] for i in g], [texts[i] for i in g], self.part_chars)]
            parts = [els for els, _ in requests]
            view.set_parts(pkg_id, [[e.id for e in part] for part in parts])
            self._large_packages.append((pkg_id, tr, parts, own))
            for k, (_, body) in enumerate(requests, 1):
                v = pv.module_summary(ix.qualified_name(pkg_id), k, len(requests), body, self.part_chars)
                if v.cut:  # repack keeps parts within the limit: this would be a fault
                    self.truncated += 1
                    llm.truncated(tr.locator(), v.cut)
                t = CURRENT["module-summary"]
                self._first.append(Request(an.PART, pkg_id, tr, partial(
                    ask, t, with_context(t, v.values, context), notes=v.notes), module=k))

    # -- rounds ---------------------------------------------------------------------------------
    def run(self, progress: Progress, name: str, concurrency: int) -> None:
        while batch := self.next_round():
            label = name if self._round == 1 else f"{name} (summaries of summaries)"
            self.fold(batch, answer(batch, progress, label, concurrency))

    def next_round(self) -> list[Request]:
        """The requests of the next round: the first, then those built on its answers."""
        self._round += 1
        if self._round == 1:
            return self._first
        batch = self._wholes() if self._round == 2 else []
        self._steps = {}
        for pkg_id, tr, parts, own in self._large_packages:
            if any(text for _, text in self._levels[pkg_id]):  # else done, or nothing to build on
                self._steps[pkg_id] = self._synthesis_requests(pkg_id, tr, parts, own, self._levels[pkg_id])
                batch += [req for _, req in self._steps[pkg_id] if req is not None]
        return batch

    def fold(self, batch: list[Request], answers: list[Any]) -> None:
        """The answers to a round, as annotations, in request order."""
        for req, res in zip(batch, answers, strict=True):
            if res is None or (self._round > 1 and req.kind is not an.DIAGRAM):
                continue  # no answer; or a package's synthesis, folded by its level below
            text, deriv = res
            cls, text = split_class(deriv.template, text)  # a candidate's class (plan GS)
            tr = req.trace.with_(derivation=deriv)
            if req.kind is an.IMAGE:
                self.images[req.key] = res
            elif req.kind in (an.MODULE, an.PART):
                self.annotations.setdefault(req.key, []).append(
                    Annotation(req.kind.label, text, tr, module=req.module, kind=req.kind, about_class=cls))
                self._described[(req.key, req.module)] = text  # type: ignore[index]
            else:  # a diagram, a large one as a whole, or a package's summary
                self.annotations.setdefault(req.key, []).append(
                    Annotation(req.kind.label, text, tr, kind=req.kind, about_class=cls))
        if self._round == 1:  # each large package's current level: ((first part, last part), summary or None)
            self._levels = {pkg_id: [((k, k), self._described.get((pkg_id, k))) for k in range(1, len(parts) + 1)]
                            for pkg_id, _, parts, _ in self._large_packages}
            return
        results = dict(zip(map(id, batch), answers, strict=True))
        for pkg_id, step in self._steps.items():
            level: Level = []
            for run, req in step:
                if req is None:  # carried up as it is
                    level += run
                    continue
                res = results[id(req)]
                cls, text = split_class(res[1].template, res[0]) if res else (None, None)
                if req.kind is an.RUN:
                    assert req.parts is not None
                    level.append((req.parts, text))
                if res is not None:
                    label = an.SUMMARY.label if req.kind is an.SUMMARY else \
                        f"{an.RUN.label} {req.parts[0]} to {req.parts[1]}"  # type: ignore[index]
                    self.annotations[pkg_id].append(Annotation(label, text, req.trace.with_(derivation=res[1]),
                                                               parts=req.parts, kind=req.kind, about_class=cls))
            self._levels[pkg_id] = level  # empty once the whole package is summarized

    def _wholes(self) -> list[Request]:
        """Large diagrams as a whole, from their modules' descriptions (plan DV-04)."""
        out = []
        for dia_id, part, tr, rel in self._large_diagrams:
            texts = [self._described.get((dia_id, m.num)) for m in part.modules]
            if not any(texts):
                continue  # the module requests got no answer: nor would this one
            el = self.ix.elements[dia_id]
            v = pv.diagram_synthesis(self.ix, part, self.ix.diagrams[dia_id], texts)  # type: ignore[arg-type]
            t = CURRENT["diagram-synthesis"]
            values = with_context(t, v.values, partial(pv.diagram_context, self.ix, part.graph, self.ix.diagrams[dia_id]))
            call = partial(_ask_with_image, self.llm, t, values, self.root, rel,
                           "image/png", project=self.content.token,
                           inputs=(self.view.trace(el).locator(), tr.locator()), notes=v.notes)
            out.append(Request(an.DIAGRAM, dia_id, tr, call))
        return out

    def _synthesis_requests(self, pkg_id: str, tr: Trace, parts: list[list[Element]], own: str,
                            level: Level) -> list[tuple[Level, Request | None]]:
        """The next step in summarizing a large package from its parts' summaries: a request for
        the whole package, or, when there are more than MAX_SUMMARIES, one per run of them. A run
        of one summary is carried up as it is, without a request."""
        n = -(-len(level) // MAX_SUMMARIES)
        runs = [level[i * len(level) // n:(i + 1) * len(level) // n] for i in range(n)]
        out: list[tuple[Level, Request | None]] = []
        for run in runs:
            a, b = run[0][0][0], run[-1][0][1]
            whole = len(runs) == 1
            if len(run) == 1 and not whole:
                out.append((run, None))
                continue
            v = pv.package_synthesis(self.ix.qualified_name(pkg_id), [len(p) for p in parts], own, run, whole)
            t = CURRENT["package-synthesis"]
            values = with_context(t, v.values, partial(pv.package_context, self.ix, pkg_id))
            call = partial(self.llm.ask, t, values, project=self.content.token,
                           inputs=(tr.locator(),), notes=v.notes)
            out.append((run, Request(an.SUMMARY, pkg_id, tr, call) if whole else
                        Request(an.RUN, pkg_id, tr, call, parts=(a, b))))
        return out

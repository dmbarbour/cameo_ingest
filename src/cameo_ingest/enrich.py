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
from . import diagrams as dg
from . import modules as mod
from . import prompt_values as pv
from .annotations import Annotation
from .emit import ProjectWriter
from .llm import LLM
from .model import Element
from .progress import Progress
from .prompt_values import Level
from .prompts import CURRENT, MAX_SUMMARIES, PART_CHARS, SUMMARY_CHARS, Template
from .provenance import ContentInfo, Derivation, Trace

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


def _ask_with_image(llm: LLM, template: Template, values: dict[str, str], root: Path, rel: str, mime: str,
                    image_pixels: int = 0, notes: dict | None = None, **kw: Any) -> Any:
    # The image is read back from disk only when the request runs, so queued requests
    # don't hold every diagram in memory.
    data = (root / rel).read_bytes()
    notes = dict(notes or {})
    if image_pixels:  # the model sees at most image_pixels anyway: send no more (FU-012R3, FU-015)
        data, mime, scaled = dg.fit_image(data, mime, image_pixels)
        if scaled:
            notes["scaled"] = scaled
    return llm.ask(template, values, image=data, mime=mime, image_path=rel, notes=notes, **kw)


def package_parts(writer: ProjectWriter, sections: list[Element], texts: list[str]) -> list[list[int]]:
    """A large package's sections (indices), in parts of related elements: by nesting,
    relationships and order, each of PART_CHARS where the sections allow (plan DV-05)."""
    index = {e.id: i for i, e in enumerate(sections)}

    def section_of(el_id: str | None) -> int | None:
        """The section an element is in: its own, or its nearest owner's."""
        while el_id is not None and el_id not in index:
            el = writer.ix.elements.get(el_id)
            el_id = el.owner if el else None
        return index.get(el_id) if el_id else None

    parents = [section_of(e.owner) for e in sections]
    links = [(a, b) for r in writer.rels
             if (a := section_of(r.source)) is not None and (b := section_of(r.target)) is not None and a != b]
    return mod.sequence_partition([len(t) + 1 for t in texts], parents, links, *PART_CHARS)


class Enricher:
    """A project's LLM requests, and their answers as annotations (`annotations`, by element)
    and image descriptions (`images`, by archive entry)."""

    def __init__(self, llm: LLM, writer: ProjectWriter, annotations: dict[str, list[Annotation]],
                 content: ContentInfo, root: Path, image_pixels: int):
        self.llm, self.writer, self.annotations = llm, writer, annotations
        self.ix, self.content, self.root, self.image_pixels = writer.ix, content, root, image_pixels
        self.images: dict[str, tuple[str, Derivation]] = {}
        self.truncated = 0  # LLM inputs cut short to fit the prompt
        self._first: list[Request] = []
        self._large_diagrams: list[tuple[str, mod.Partition, Trace, str]] = []
        self._large_packages: list[tuple[str, Trace, list[list[Element]], str]] = []
        self._described: dict[tuple[str, int], str] = {}  # modules of large diagrams, parts of large packages
        self._levels: dict[str, Level] = {}
        self._steps: dict[str, list[tuple[Level, Request | None]]] = {}
        self._round = 0

    # -- the first round ------------------------------------------------------------------------
    def diagram(self, dia_id: str, tr: Trace, rel: str) -> None:
        """A diagram whose sketch is drawn at `rel`: a description, unless there is too little
        to describe (FU-010)."""
        ix, writer, llm = self.ix, self.writer, self.llm
        el, graph = ix.elements[dia_id], writer.graph(dia_id)
        if not llm.cfg.vision_model or graph is None:
            return
        if graph.trivial():
            llm.skip(writer.trace(el).locator(), "skipped_trivial",
                     f"{len(graph.nodes)} shape(s), {len(graph.links)} connection(s)")
            return
        v = pv.diagram_description(ix, graph, ix.diagrams[dia_id])
        if v.cut:
            self.truncated += 1
            llm.truncated(writer.trace(el).locator(), v.cut)
        call = partial(_ask_with_image, llm, CURRENT["diagram-description"], v.values, self.root, rel, "image/png",
                       project=self.content.token, inputs=(writer.trace(el).locator(), tr.locator()), notes=v.notes)
        self._first.append(Request(an.DIAGRAM, dia_id, tr, call))

    def module(self, dia_id: str, part: mod.Partition, num: int, tr: Trace, rel: str) -> None:
        """Module `num` of a large diagram, whose sketch is drawn at `rel`."""
        if not self.llm.cfg.vision_model:
            return
        ix, writer = self.ix, self.writer
        v = pv.module_description(ix, writer.graph(dia_id), part, num, ix.diagrams[dia_id])
        call = partial(_ask_with_image, self.llm, CURRENT["module-description"], v.values, self.root, rel,
                       "image/png", project=self.content.token,
                       inputs=(writer.trace(ix.elements[dia_id]).locator(), tr.locator()), notes=v.notes)
        self._first.append(Request(an.MODULE, dia_id, tr, call, num))

    def large_diagram(self, dia_id: str, part: mod.Partition, tr: Trace, rel: str) -> None:
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
        ix, writer, llm = self.ix, self.writer, self.llm
        if not llm.cfg.text_model:
            return
        for pkg_id in writer.pkg_file:
            pkg = ix.elements[pkg_id]
            sections = writer.sections_in(pkg)
            if len(sections) < MIN_SECTIONS_FOR_SUMMARY:
                continue
            # Plain text, without link targets or trace lines (AR-018): the prompt, and so the
            # cached answer, depends only on the model's content, not on where it was found.
            own = writer.section_view(pkg, generated=False).text()
            texts = [writer.section_view(e, generated=False).text() for e in sections]
            tr = writer.trace(pkg)
            text = "\n\n".join([own, *texts])
            ask = partial(llm.ask, project=self.content.token, inputs=(tr.locator(),))
            if len(text) <= SUMMARY_CHARS:
                self._first.append(Request(an.SUMMARY, pkg_id, tr, partial(
                    ask, CURRENT["package-summary"], pv.package_summary(text).values)))
                continue
            if sum(e.kind == "InstanceSpecification" for e in sections) >= INSTANCE_SHARE * len(sections):
                v = pv.instances_summary(ix, ix.qualified_name(pkg_id), own, sections, texts)
                self._first.append(Request(an.SUMMARY, pkg_id, tr, partial(
                    ask, CURRENT["instances-summary"], v.values, notes=v.notes)))
                continue
            parts = [[sections[i] for i in g] for g in package_parts(writer, sections, texts)]
            writer.set_parts(pkg_id, [[e.id for e in part] for part in parts])
            self._large_packages.append((pkg_id, tr, parts, own))
            for k, part in enumerate(parts, 1):
                v = pv.module_summary(ix.qualified_name(pkg_id), k, len(parts),
                                      "\n\n".join(texts[sections.index(e)] for e in part))
                if v.cut:  # a single section over the limit
                    self.truncated += 1
                    llm.truncated(tr.locator(), v.cut)
                self._first.append(Request(an.PART, pkg_id, tr, partial(
                    ask, CURRENT["module-summary"], v.values, notes=v.notes), module=k))

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
            tr = req.trace.with_(derivation=deriv)
            if req.kind is an.IMAGE:
                self.images[req.key] = res
            elif req.kind in (an.MODULE, an.PART):
                self.annotations.setdefault(req.key, []).append(
                    Annotation(req.kind.label, text, tr, module=req.module, kind=req.kind))
                self._described[(req.key, req.module)] = text  # type: ignore[index]
            else:  # a diagram, a large one as a whole, or a package's summary
                self.annotations.setdefault(req.key, []).append(Annotation(req.kind.label, text, tr, kind=req.kind))
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
                if req.kind is an.RUN:
                    assert req.parts is not None
                    level.append((req.parts, res[0] if res else None))
                if res is not None:
                    label = an.SUMMARY.label if req.kind is an.SUMMARY else \
                        f"{an.RUN.label} {req.parts[0]} to {req.parts[1]}"  # type: ignore[index]
                    self.annotations[pkg_id].append(Annotation(label, res[0], req.trace.with_(derivation=res[1]),
                                                               parts=req.parts, kind=req.kind))
            self._levels[pkg_id] = level  # empty once the whole package is summarized

    def _wholes(self) -> list[Request]:
        """Large diagrams as a whole, from their modules' descriptions (plan DV-04)."""
        out = []
        for dia_id, part, tr, rel in self._large_diagrams:
            texts = [self._described.get((dia_id, m.num)) for m in part.modules]
            if not any(texts):
                continue  # the module requests got no answer: nor would this one
            el = self.ix.elements[dia_id]
            v = pv.diagram_synthesis(self.ix, self.writer.graph(dia_id), part, self.ix.diagrams[dia_id], texts)  # type: ignore[arg-type]
            call = partial(_ask_with_image, self.llm, CURRENT["diagram-synthesis"], v.values, self.root, rel,
                           "image/png", project=self.content.token,
                           inputs=(self.writer.trace(el).locator(), tr.locator()), notes=v.notes)
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
            call = partial(self.llm.ask, CURRENT["package-synthesis"], v.values, project=self.content.token,
                           inputs=(tr.locator(),), notes=v.notes)
            out.append((run, Request(an.SUMMARY, pkg_id, tr, call) if whole else
                        Request(an.RUN, pkg_id, tr, call, parts=(a, b))))
        return out

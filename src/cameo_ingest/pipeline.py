"""Per-project pipeline: parse -> (render) -> (enrich) -> emit."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

from . import diagrams as dg
from . import modules as mod
from . import semantics as sem
from .archive import Project, first_tag
from .emit import Annotation, Outputs, ProjectWriter, slug
from .layout import Layout, parse_layout
from .llm import LLM
from .model import Element, ModelIndex
from .progress import QUIET, Progress
from .prompts import CURRENT, Template
from .provenance import ContentInfo, Derivation, Trace
from .text import front_matter, plural
from .xmi import finalize, parse_into

log = logging.getLogger(__name__)

IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}
MIN_SECTIONS_FOR_SUMMARY = 5
SUMMARY_INPUT_CHARS = 12000  # package text sent for a summary; larger packages are summarized in parts
PART_CHARS = (3000, 12000)  # a large package's parts: the smallest worth its own request, and the limit
OWN_CHARS = 6000  # a large package's own section, sent with its parts' summaries
MAX_SUMMARIES = 30  # summaries per synthesis request; more are summarized in runs first
DIAGRAM_CONTEXT_ITEMS = 150  # shapes, and connections, listed with a diagram image

@dataclass
class ProjectResult:
    outputs: Outputs
    summary: dict[str, Any] = field(default_factory=dict)


class _Counting:
    """Reports the bytes read from a stream, for parsing progress."""

    def __init__(self, f: Any, advance: Callable[[int], None]):
        self._f, self._advance = f, advance

    def read(self, n: int = -1) -> bytes:
        data = self._f.read(n)
        self._advance(len(data))
        return data


def parse_project(project: Project, progress: Progress = QUIET) -> ModelIndex:
    ix = ModelIndex()
    total = sum(project.size(e) for e in project.model_entries)
    with progress.phase(f"{project.display_name}: parsing", total, "B") as ph:
        for entry in project.model_entries:
            with project.open(entry) as f:
                parse_into(ix, _Counting(f, ph.advance), entry)
        finalize(ix)
    log.info("%s: %s elements, %s diagrams, %s stereotype applications", project.display_name,
             f"{len(ix.elements):,}", f"{len(ix.diagrams):,}", f"{len(ix.stereotypes):,}")
    return ix


def load_layouts(project: Project, ix: ModelIndex, progress: Progress = QUIET) -> dict[str, Layout]:
    """Parse each diagram's layout stream; record which elements it shows."""
    names = set(project.entry_names)
    todo = [(d, [s for s in d.streams if s in names]) for d in ix.diagrams.values()]
    todo = [(d, streams) for d, streams in todo if streams]
    out: dict[str, Layout] = {}
    with progress.phase(f"{project.display_name}: layouts", len(todo), "diagram") as ph:
        for d, streams in todo:
            layout = Layout()
            for s in streams:
                with project.open(s) as f:
                    tag = first_tag(f.read(4096))
                if tag is None or tag.split(":")[-1] != "mdOwnedViews":
                    continue  # an attachment stream, not a layout
                try:
                    with project.open(s) as f:
                        layout.views += parse_layout(f).views
                except Exception as e:  # malformed stream: keep going
                    log.warning("diagram %s: cannot parse layout %s: %s", d.id, s, e)
            for v in layout.views:
                if v.element and v.element not in ix.elements and "#" in v.element:
                    own = v.element.rpartition("#")[2]
                    if own in ix.elements:  # the project's own element, named through its file (FU-019)
                        v.element = own
            if layout.views:
                out[d.id] = layout
                d.shown = list(dict.fromkeys(d.shown + [e for e in layout.elements() if e in ix.elements]))
            ph.advance()
    return out


def _image_mime(head: bytes) -> str | None:
    for magic, mime in IMAGE_MAGIC.items():
        if head.startswith(magic):
            return mime
    return None


@dataclass
class _Request:
    """One LLM request, made after rendering so that requests can run in parallel."""

    kind: str  # "diagram", "module", "image" or "summary"
    key: str  # diagram id, image entry or package id
    trace: Trace
    call: Callable[[], Any]
    module: int | None = None  # of a large diagram, or part of a large package
    parts: tuple[int, int] | None = None  # a run of a large package's parts


def _ask_with_image(llm: LLM, template: Template, values: dict[str, str], root: Path, rel: str, mime: str,
                    image_pixels: int = 0, notes: dict | None = None, **kw: Any) -> Any:
    # The image is read back from disk only when the request runs, so queued requests
    # don't hold every diagram in memory.
    data = (root / rel).read_bytes()
    notes = dict(notes or {})
    if image_pixels:  # the model sees at most image_pixels anyway: send no more (FU-012R3, FU-015)
        data, mime, scaled = _fit_image(data, mime, image_pixels)
        if scaled:
            notes["scaled"] = scaled
    return llm.ask(template, values, image=data, mime=mime, image_path=rel, notes=notes, **kw)


def _fit_image(data: bytes, mime: str, pixels: int) -> tuple[bytes, str, dict | None]:
    """The image scaled down to at most `pixels`, sides in multiples of 48, as PNG; unchanged
    if it already fits or can't be read."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if w * h <= pixels:
                return data, mime, None
            f = (pixels / (w * h)) ** 0.5
            size = (max(dg.PATCH_PX, int(w * f) // dg.PATCH_PX * dg.PATCH_PX),
                    max(dg.PATCH_PX, int(h * f) // dg.PATCH_PX * dg.PATCH_PX))
            buf = io.BytesIO()
            img.convert("RGB").resize(size, Image.LANCZOS).save(buf, "PNG")
            return buf.getvalue(), "image/png", {"from": [w, h], "to": list(size)}
    except Exception as e:  # a damaged or unusual image is sent as it is
        log.debug("cannot scale an image: %s", e)
        return data, mime, None


def _answer(requests: list[_Request], progress: Progress, label: str, concurrency: int) -> list[Any]:
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


def part_values(package: str, k: int, n: int, body: str) -> tuple[dict[str, str], dict[str, Any]]:
    """The text slots and notes of a module-summary request for part `k` of `n`."""
    notes: dict[str, Any] = {"part": f"{k} of {n}"}
    cut_note = ""
    if len(body) > PART_CHARS[1]:
        notes["truncated"] = {"characters": len(body), "limit": PART_CHARS[1]}
        cut_note = f"The text was cut at {PART_CHARS[1]:,} of its {len(body):,} characters, so its end is missing. "
    return {"CUT_NOTE": cut_note, "PACKAGE": package, "PART": f"{k} of {n}", "SECTIONS": body[:PART_CHARS[1]]}, notes


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


Level = list[tuple[tuple[int, int], str | None]]  # (first part, last part), summary


def synthesis_values(package: str, sizes: list[int], own: str, run: Level, whole: bool) -> dict[str, str]:
    """The text slots of a package-synthesis request over `run` of a package whose parts
    have `sizes` elements."""
    a, b = run[0][0][0], run[-1][0][1]
    summaries = "\n\n".join(
        (f"Part {x} ({plural(sizes[x - 1], 'element')}): " if x == y else f"Parts {x} to {y}: ")
        + (text or "(not summarized)") for (x, y), text in run)
    return {"SCOPE": "the whole package" if whole else f"parts {a} to {b} of {len(sizes)}",
            "CUT_NOTE": (f"The package's own section was cut at {OWN_CHARS:,} of its {len(own):,} characters. "
                         if len(own) > OWN_CHARS else ""),
            "PACKAGE": package, "PACKAGE_TEXT": own[:OWN_CHARS], "SUMMARIES": summaries}


def _synthesis_requests(llm: LLM, content: ContentInfo, ix: ModelIndex, pkg_id: str, tr: Trace,
                        parts: list[list[Element]], own: str, level: Level) -> list[tuple[Level, _Request | None]]:
    """The next step in summarizing a large package from its parts' summaries: a request for
    the whole package, or, when there are more than MAX_SUMMARIES, one per run of them. A run
    of one summary is carried up as it is, without a request."""
    n = -(-len(level) // MAX_SUMMARIES)
    runs = [level[i * len(level) // n:(i + 1) * len(level) // n] for i in range(n)]
    out: list[tuple[Level, _Request | None]] = []
    for run in runs:
        a, b = run[0][0][0], run[-1][0][1]
        whole = len(runs) == 1
        if len(run) == 1 and not whole:
            out.append((run, None))
            continue
        values = synthesis_values(ix.qualified_name(pkg_id), [len(p) for p in parts], own, run, whole)
        call = partial(llm.ask, CURRENT["package-synthesis"], values, project=content.token, inputs=(tr.locator(),),
                       notes={"parts": len(parts), "scope": values["SCOPE"]})
        out.append((run, _Request("summary", pkg_id, tr, call) if whole else
                       _Request("run", pkg_id, tr, call, parts=(a, b))))
    return out


def _draw(path: Path, draw: Callable[[], bytes | None]) -> bool:
    """Write a sketch unless an interrupted attempt already did (a sketch on disk is always
    complete); False when there is nothing to draw."""
    if path.exists():
        return True
    png = draw()
    if png is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(png)
    tmp.replace(path)
    return True


SKETCH = "re-drawn from layout data, not a Cameo rendering"


def ingest_project(content: ContentInfo, project: Project, root: Path, llm: LLM, render: bool = True,
                   progress: Progress = QUIET, concurrency: int = 1, image_pixels: int = dg.IMAGE_PIXELS,
                   modules: tuple[int, int, int] = mod.DEFAULTS) -> ProjectResult:
    ix = parse_project(project, progress)
    annotations: dict[str, list[Annotation]] = {}
    base = Trace(content_sha256=content.sha256)
    layouts = load_layouts(project, ix, progress)
    writer = ProjectWriter(content, project, ix, root, annotations, layouts, modules)
    requests: list[_Request] = []
    large: list[tuple[str, mod.Partition, Trace, str]] = []  # described as a whole once their modules are
    truncated = 0  # LLM inputs cut short to fit the prompt

    reused = 0  # sketches drawn by an interrupted attempt with the same tool and options
    if render and layouts:
        with progress.phase(f"{project.display_name}: rendering", len(layouts), "diagram") as ph:
            for dia_id in layouts:
                ph.advance()
                d = ix.diagrams[dia_id]
                el = ix.elements[dia_id]
                graph = writer.graph(dia_id)
                part = writer.partition(dia_id)  # a large diagram: an overview and a view per module (plan DV)
                title = f"{d.diagram_type or 'Diagram'}: {ix.qualified_name(dia_id)}"
                rel = writer.dia_file[dia_id].removesuffix(".md") + ".png"
                reused += (root / rel).exists()
                if part is not None:
                    drawn = _draw(root / rel, partial(mod.overview_png, ix, graph, part, title, image_pixels))
                else:
                    drawn = _draw(root / rel, partial(dg.render_png, ix, graph, title, pixels=image_pixels))
                if not drawn:
                    continue
                writer.out.files.append(root / rel)
                tr = writer.trace(el).with_(entry=d.streams[0] if d.streams else el.entry, line=None,
                                            derivation=Derivation(method="rendered", inputs=tuple(d.streams)))
                label = f"Diagram sketch with its modules outlined ({SKETCH})" if part else f"Diagram sketch ({SKETCH})"
                annotations.setdefault(dia_id, []).append(Annotation(label, "", tr, image=rel))
                diagram = f"{d.name} ({d.diagram_type})"
                if part is not None:
                    for m in part.modules:
                        mrel = writer.module_image(dia_id, m.num)
                        if not _draw(root / mrel, partial(mod.module_png, ix, graph, part, m.num, title, image_pixels)):
                            continue
                        writer.out.files.append(root / mrel)
                        annotations[dia_id].append(
                            Annotation(f"Module M{m.num} sketch ({SKETCH})", "", tr, image=mrel, module=m.num))
                        if llm.cfg.vision_model:
                            call = partial(_ask_with_image, llm, CURRENT["module-description"],
                                           mod.module_values(ix, graph, part, m.num, diagram), root, mrel,
                                           "image/png", project=content.token,
                                           inputs=(writer.trace(el).locator(), tr.locator()),
                                           notes={"module": f"M{m.num} of {len(part.modules)}"})
                            requests.append(_Request("module", dia_id, tr, call, m.num))
                    large.append((dia_id, part, tr, rel))
                elif llm.cfg.vision_model and graph.trivial():  # nothing to describe (FU-010)
                    llm.skip(writer.trace(el).locator(), "skipped_trivial",
                             f"{len(graph.nodes)} shape(s), {len(graph.links)} connection(s)")
                elif llm.cfg.vision_model:
                    nodes, edges = dg.describe(ix, graph, lambda e: ix.label(e))
                    notes, cut_note = {}, ""
                    if max(len(nodes), len(edges)) > DIAGRAM_CONTEXT_ITEMS:
                        truncated += 1
                        llm.truncated(writer.trace(el).locator(), f"{len(nodes)} shapes, {len(edges)} connections; "
                                                                  f"the first {DIAGRAM_CONTEXT_ITEMS} of each sent")
                        notes = {"truncated": {"shapes": len(nodes), "connections": len(edges),
                                               "limit": DIAGRAM_CONTEXT_ITEMS}}
                        cut_note = (f"\n(Only the first {DIAGRAM_CONTEXT_ITEMS} shapes and connections are listed: "
                                    f"the diagram has {len(nodes)} shapes and {len(edges)} connections.)")
                    values = {"DIAGRAM": diagram,
                              "LEGEND": "\n".join(nodes[:DIAGRAM_CONTEXT_ITEMS]),
                              "CONNECTIONS": "\n".join(edges[:DIAGRAM_CONTEXT_ITEMS]) or "(none)",
                              "CUT_NOTE": cut_note}
                    call = partial(_ask_with_image, llm, CURRENT["diagram-description"], values, root, rel, "image/png",
                                   project=content.token, inputs=(writer.trace(el).locator(), tr.locator()),
                                   notes=notes)
                    requests.append(_Request("diagram", dia_id, tr, call))

    if reused:
        log.info("%s: reused %d sketch(es) drawn by an interrupted run", project.display_name, reused)

    # Embedded images (attachments, image shapes...). Linking them to elements depends on
    # version-specific storage, so they are listed at project level for now.
    image_notes = []
    for entry in project.entry_names:
        if entry in project.model_entries or project.size(entry) < 64:
            continue
        with project.open(entry) as f:
            mime = _image_mime(f.read(8))
        if not mime:
            continue
        rel = f"images/{slug(PurePosixPath(entry).name, 100)}.{mime.split('/')[1]}"
        writer.root.joinpath(rel).parent.mkdir(parents=True, exist_ok=True)
        writer.root.joinpath(rel).write_bytes(project.read(entry))
        writer.out.files.append(writer.root / rel)
        tr = base.with_(entry=entry)
        image_notes.append((entry, rel, tr))
        if llm.cfg.vision_model:
            call = partial(_ask_with_image, llm, CURRENT["image-description"], {}, writer.root, rel, mime, image_pixels=image_pixels,
                           project=content.token, inputs=(tr.locator(),))
            requests.append(_Request("image", entry, tr, call))

    # Package summaries from the deterministic text, so the LLM only rephrases what is there.
    # A large package is summarized in parts, and then from its parts' summaries (FU-005).
    large_packages: list[tuple[str, Trace, list[list[Element]], str]] = []
    if llm.cfg.text_model:
        for pkg_id, rel in writer.pkg_file.items():
            pkg = ix.elements[pkg_id]
            sections = writer._section_elements_in(pkg)
            if len(sections) < MIN_SECTIONS_FOR_SUMMARY:
                continue
            # Without trace lines: the prompt, and so the cached answer, then depends only on
            # the model's content, not on which file or bundle it was found in.
            own = writer.section(pkg, rel, 1, trace=False)
            texts = [writer.section(e, rel, 2, trace=False) for e in sections]
            tr = writer.trace(pkg)
            text = own + "\n".join(texts)
            if len(text) <= SUMMARY_INPUT_CHARS:
                call = partial(llm.ask, CURRENT["package-summary"], {"CUT_NOTE": "", "PACKAGE_TEXT": text},
                               project=content.token, inputs=(tr.locator(),))
                requests.append(_Request("summary", pkg_id, tr, call))
                continue
            parts = [[sections[i] for i in g] for g in package_parts(writer, sections, texts)]
            writer.package_parts[pkg_id] = [[e.id for e in part] for part in parts]
            large_packages.append((pkg_id, tr, parts, own))
            qn = ix.qualified_name(pkg_id)
            for k, part in enumerate(parts, 1):
                body = "\n".join(texts[sections.index(e)] for e in part)
                values, notes = part_values(qn, k, len(parts), body)
                if "truncated" in notes:  # a single section over the limit
                    truncated += 1
                    llm.truncated(tr.locator(), f"part {k}: {len(body):,} characters; the first {PART_CHARS[1]:,} sent")
                call = partial(llm.ask, CURRENT["module-summary"], values, project=content.token,
                               inputs=(tr.locator(),), notes=notes)
                requests.append(_Request("part", pkg_id, tr, call, module=k))

    if truncated:
        log.warning("%s: %d LLM input(s) were cut short to fit the prompt (element sections over %s characters, "
                    "diagrams over %d shapes or connections)", project.display_name, truncated,
                    f"{PART_CHARS[1]:,}", DIAGRAM_CONTEXT_ITEMS)

    image_desc: dict[str, tuple[str, Derivation]] = {}
    described: dict[tuple[str, int], str] = {}  # modules of large diagrams, parts of large packages
    for req, res in zip(requests, _answer(requests, progress, project.display_name, concurrency), strict=True):
        if res is None:
            continue
        text, deriv = res
        if req.kind == "diagram":
            annotations[req.key].append(Annotation("Diagram description", text, req.trace.with_(derivation=deriv)))
        elif req.kind in ("module", "part"):
            assert req.module is not None
            label = "Module description" if req.kind == "module" else "Part summary"
            annotations.setdefault(req.key, []).append(
                Annotation(label, text, req.trace.with_(derivation=deriv), module=req.module))
            described[(req.key, req.module)] = text
        elif req.kind == "summary":
            annotations.setdefault(req.key, []).append(Annotation("Summary", text, req.trace.with_(derivation=deriv)))
        else:
            image_desc[req.key] = res

    # Then, a round at a time: large diagrams as a whole from their modules' descriptions
    # (plan DV-04), and large packages from their parts' summaries, through runs of at most
    # MAX_SUMMARIES summaries while there are more (DV-05).
    wholes = []
    for dia_id, part, tr, rel in large:
        texts = [described.get((dia_id, m.num)) for m in part.modules]
        if not any(texts):
            continue  # the module requests got no answer: nor would this one
        d, el = ix.diagrams[dia_id], ix.elements[dia_id]
        values = mod.synthesis_values(ix, writer.graph(dia_id), part, f"{d.name} ({d.diagram_type})", texts)  # type: ignore[arg-type]
        missing = sum(t is None for t in texts)
        call = partial(_ask_with_image, llm, CURRENT["diagram-synthesis"], values, root, rel, "image/png",
                       project=content.token, inputs=(writer.trace(el).locator(), tr.locator()),
                       notes={"modules": len(part.modules), **({"undescribed": missing} if missing else {})})
        wholes.append(_Request("diagram", dia_id, tr, call))
    # Each large package's current level: ((first part, last part), summary or None).
    levels: dict[str, Level] = {pkg_id: [((k, k), described.get((pkg_id, k))) for k in range(1, len(parts) + 1)]
                                for pkg_id, _, parts, _ in large_packages}
    while True:
        batch, wholes = wholes, []
        steps: dict[str, list[tuple[Level, _Request | None]]] = {}
        for pkg_id, tr, parts, own in large_packages:
            if any(text for _, text in levels[pkg_id]):  # else done, or nothing to build on
                steps[pkg_id] = _synthesis_requests(llm, content, ix, pkg_id, tr, parts, own, levels[pkg_id])
                batch += [req for _, req in steps[pkg_id] if req is not None]
        if not batch:
            break
        answers = dict(zip(map(id, batch), _answer(batch, progress, f"{project.display_name} (summaries of summaries)",
                                                   concurrency), strict=True))
        for req in batch:
            if req.kind == "diagram" and answers[id(req)] is not None:  # a large diagram as a whole
                text, deriv = answers[id(req)]
                annotations[req.key].append(Annotation("Diagram description", text, req.trace.with_(derivation=deriv)))
        for pkg_id, step in steps.items():
            level: Level = []
            for run, req in step:
                if req is None:  # carried up as it is
                    level += run
                    continue
                res = answers[id(req)]
                if req.kind == "run":
                    assert req.parts is not None
                    level.append((req.parts, res[0] if res else None))
                if res is not None:
                    label = "Summary" if req.kind == "summary" else f"Summary of parts {req.parts[0]} to {req.parts[1]}"  # type: ignore[index]
                    annotations[pkg_id].append(Annotation(label, res[0], req.trace.with_(derivation=res[1]),
                                                          parts=req.parts))
            levels[pkg_id] = level  # empty once the whole package is summarized

    if image_notes:
        lines = ["# Embedded images", ""]
        for entry, rel, tr in image_notes:
            lines += [f"## {entry}", "", f"![{entry}]({rel})", ""]
            if entry in image_desc:
                text, deriv = image_desc[entry]
                lines += [f"**Description** _(generated by {deriv.model}; not part of the source model)_:",
                          "", text, ""]
                labelled = (f"Description of embedded image {entry} (generated by {deriv.model}; not part of "
                            f"the source model)\n\n{text}")
                writer.chunk(kind="generated:image_description", title=f"Image description: {entry}",
                             text=labelled, file="images.md", el=None, trace=tr.with_(derivation=deriv), salt=entry)
            lines += [f"<sub>trace: `{tr.locator()}`</sub>", ""]
        fm = front_matter({"title": f"Embedded images in {content.name}", "kind": "images",
                           "provenance": writer.file_provenance(trace=base.to_dict())})
        writer.write_text("images.md", fm + "\n".join(lines))

    with progress.phase(f"{project.display_name}: writing", writer.write_steps(), "step") as ph:
        out = writer.write_all(tick=ph.advance)

    summary = {
        "name": content.name,
        "model_entries": project.model_entries,
        "exporter": ix.exporter,
        "elements": len(ix.elements),
        "diagrams": len(ix.diagrams),
        "stereotype_applications": len(ix.stereotypes),
        "relationships": len(writer.rels),
        "requirements": sum(1 for e in ix.elements.values() if sem.is_requirement(ix, e)),
        "images": len(image_notes),
    }
    return ProjectResult(out, summary)

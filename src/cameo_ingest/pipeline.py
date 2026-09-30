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
from . import semantics as sem
from .archive import Project, first_tag
from .emit import Annotation, Outputs, ProjectWriter, slug
from .layout import Layout, parse_layout
from .llm import LLM
from .model import ModelIndex
from .progress import QUIET, Progress
from .provenance import ContentInfo, Derivation, Trace
from .text import front_matter
from .xmi import finalize, parse_into

log = logging.getLogger(__name__)

IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}
MIN_SECTIONS_FOR_SUMMARY = 5
SUMMARY_INPUT_CHARS = 12000  # package text sent for a summary
DIAGRAM_CONTEXT_ITEMS = 150  # shapes, and connections, listed with a diagram image

PACKAGE_SUMMARY_PROMPT = (
    "You are documenting a systems engineering model (UML/SysML, authored in Cameo). Below is an "
    "extract of one package. Write a concise factual summary (at most 150 words) of what this package "
    "models: its purpose, the main elements and how they relate. Use only the information given; do "
    "not speculate. Plain prose, no headings."
)
DIAGRAM_PROMPT = (
    "This is a simplified re-drawing of a Cameo (UML/SysML) diagram: boxes, labels and connector lines "
    "only, generated from layout data. The authoritative list of shapes and connections follows the "
    "instructions. Describe what the diagram communicates for a search index: its subject, the main "
    "elements, how they are arranged or grouped, and the key flows or relationships. Be factual, use "
    "the element names, and do not invent elements that are not listed. At most 200 words."
)
IMAGE_PROMPT = (
    "This image was embedded in a systems engineering model (Cameo/SysML). Describe its content "
    "factually for a search index: what kind of image it is, any visible text, labels, components and "
    "connections. Do not speculate beyond what is visible. At most 200 words."
)


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

    kind: str  # "diagram", "image" or "summary"
    key: str  # diagram id, image entry or package id
    trace: Trace
    call: Callable[[], Any]


def _describe_file(llm: LLM, prompt: str, path: Path, mime: str, inputs: tuple[str, ...]) -> Any:
    # The image is read back from disk only when the request runs, so queued requests
    # don't hold every diagram in memory.
    return llm.describe_image(prompt, path.read_bytes(), mime, inputs=inputs)


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


def ingest_project(content: ContentInfo, project: Project, root: Path, llm: LLM, render: bool = True,
                   progress: Progress = QUIET, concurrency: int = 1) -> ProjectResult:
    ix = parse_project(project, progress)
    annotations: dict[str, list[Annotation]] = {}
    base = Trace(content_sha256=content.sha256)
    layouts = load_layouts(project, ix, progress)
    writer = ProjectWriter(content, project, ix, root, annotations, layouts)
    requests: list[_Request] = []
    truncated = 0  # LLM inputs cut short to fit the prompt

    reused = 0  # sketches drawn by an interrupted attempt with the same tool and options
    if render and layouts:
        with progress.phase(f"{project.display_name}: rendering", len(layouts), "diagram") as ph:
            for dia_id, layout in layouts.items():
                ph.advance()
                d = ix.diagrams[dia_id]
                el = ix.elements[dia_id]
                rel = writer.dia_file[dia_id].removesuffix(".md") + ".png"
                path = root / rel
                if path.exists():
                    reused += 1
                else:
                    png = dg.render_png(ix, layout, f"{d.diagram_type or 'Diagram'}: {ix.qualified_name(dia_id)}")
                    if png is None:
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(path.name + ".tmp")  # a sketch on disk is always complete
                    tmp.write_bytes(png)
                    tmp.replace(path)
                writer.out.files.append(path)
                tr = writer.trace(el).with_(entry=d.streams[0] if d.streams else el.entry, line=None,
                                            derivation=Derivation(method="rendered", inputs=tuple(d.streams)))
                annotations.setdefault(dia_id, []).append(
                    Annotation("Diagram sketch (re-drawn from layout data, not a Cameo rendering)", "", tr, image=rel))
                if llm.cfg.vision_model:
                    nodes, edges = dg.describe(ix, layout, lambda e: ix.label(e))
                    if max(len(nodes), len(edges)) > DIAGRAM_CONTEXT_ITEMS:
                        truncated += 1
                        llm.truncated(writer.trace(el).locator(), f"{len(nodes)} shapes, {len(edges)} connections; "
                                                                  f"the first {DIAGRAM_CONTEXT_ITEMS} of each sent")
                    context = "\n".join([f"Diagram: {d.name} ({d.diagram_type})", "Shapes:"]
                                        + nodes[:DIAGRAM_CONTEXT_ITEMS] + ["Connections:"]
                                        + edges[:DIAGRAM_CONTEXT_ITEMS])
                    call = partial(_describe_file, llm, DIAGRAM_PROMPT + "\n\n" + context, root / rel, "image/png",
                                   (writer.trace(el).locator(), tr.locator()))
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
            call = partial(_describe_file, llm, IMAGE_PROMPT, writer.root / rel, mime, (tr.locator(),))
            requests.append(_Request("image", entry, tr, call))

    # Package summaries from the deterministic text, so the LLM only rephrases what is there.
    if llm.cfg.text_model:
        for pkg_id, rel in writer.pkg_file.items():
            pkg = ix.elements[pkg_id]
            sections = writer._section_elements_in(pkg)
            if len(sections) < MIN_SECTIONS_FOR_SUMMARY:
                continue
            # Without trace lines: the prompt, and so the cached answer, then depends only on
            # the model's content, not on which file or bundle it was found in.
            text = writer.section(pkg, rel, 1, trace=False) + "\n".join(
                writer.section(e, rel, 2, trace=False) for e in sections)
            tr = writer.trace(pkg)
            if len(text) > SUMMARY_INPUT_CHARS:
                truncated += 1
                llm.truncated(tr.locator(), f"{len(text):,} characters; the first {SUMMARY_INPUT_CHARS:,} sent")
            call = partial(llm.summarize, PACKAGE_SUMMARY_PROMPT, text[:SUMMARY_INPUT_CHARS], inputs=(tr.locator(),))
            requests.append(_Request("summary", pkg_id, tr, call))

    if truncated:
        log.warning("%s: %d LLM input(s) were cut short to fit the prompt (at most %s characters of package "
                    "text, %d shapes and %d connections per diagram)", project.display_name, truncated,
                    f"{SUMMARY_INPUT_CHARS:,}", DIAGRAM_CONTEXT_ITEMS, DIAGRAM_CONTEXT_ITEMS)

    image_desc: dict[str, tuple[str, Derivation]] = {}
    for req, res in zip(requests, _answer(requests, progress, project.display_name, concurrency), strict=True):
        if res is None:
            continue
        text, deriv = res
        if req.kind == "diagram":
            annotations[req.key].append(Annotation("Diagram description", text, req.trace.with_(derivation=deriv)))
        elif req.kind == "summary":
            annotations.setdefault(req.key, []).append(Annotation("Summary", text, req.trace.with_(derivation=deriv)))
        else:
            image_desc[req.key] = res

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

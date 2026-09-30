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
from .prompts import CURRENT, Template
from .provenance import ContentInfo, Derivation, Trace
from .text import front_matter
from .xmi import finalize, parse_into

log = logging.getLogger(__name__)

IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}
MIN_SECTIONS_FOR_SUMMARY = 5
SUMMARY_INPUT_CHARS = 12000  # package text sent for a summary
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


def ingest_project(content: ContentInfo, project: Project, root: Path, llm: LLM, render: bool = True,
                   progress: Progress = QUIET, concurrency: int = 1,
                   image_pixels: int = dg.IMAGE_PIXELS) -> ProjectResult:
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
            for dia_id in layouts:
                ph.advance()
                d = ix.diagrams[dia_id]
                el = ix.elements[dia_id]
                graph = writer.graph(dia_id)
                rel = writer.dia_file[dia_id].removesuffix(".md") + ".png"
                path = root / rel
                if path.exists():
                    reused += 1
                else:
                    png = dg.render_png(ix, graph, f"{d.diagram_type or 'Diagram'}: {ix.qualified_name(dia_id)}",
                                        pixels=image_pixels)
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
                if llm.cfg.vision_model and graph.trivial():  # nothing to describe (FU-010)
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
                    values = {"DIAGRAM": f"{d.name} ({d.diagram_type})",
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
            notes, cut_note = {}, ""
            if len(text) > SUMMARY_INPUT_CHARS:
                truncated += 1
                llm.truncated(tr.locator(), f"{len(text):,} characters; the first {SUMMARY_INPUT_CHARS:,} sent")
                notes = {"truncated": {"characters": len(text), "limit": SUMMARY_INPUT_CHARS}}
                cut_note = (f"The text was cut at {SUMMARY_INPUT_CHARS:,} of its {len(text):,} characters, so the "
                            "later elements are known by name only. ")
            call = partial(llm.ask, CURRENT["package-summary"],
                           {"CUT_NOTE": cut_note, "PACKAGE_TEXT": text[:SUMMARY_INPUT_CHARS]},
                           project=content.token, inputs=(tr.locator(),), notes=notes)
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

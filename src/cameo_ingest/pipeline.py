"""Per-project pipeline: parse -> (render) -> (enrich) -> emit."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

from . import semantics as sem
from . import sketch, sketch_svg
from .annotations import Annotation
from .archive import Project, first_tag
from .config import IMAGE_PIXELS, MODULES
from .emit import ProjectWriter
from .enrich import Enricher
from .external import proxy_names
from .layout import Layout, own_elements, parse_layout
from .llm import EnrichmentSession
from .model import ModelIndex
from .progress import QUIET, Progress
from .prompts import DIAGRAM_ITEMS, PART_CHARS
from .provenance import ContentInfo, Derivation, Trace
from .text import image_mime, slug
from .xmi import finalize, parse_into

log = logging.getLogger(__name__)


@dataclass
class ProjectResult:
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
    if ix.external_refs:  # names for references into used projects (plan UL)
        ix.external = proxy_names(project)
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
            own_elements(layout, ix.elements)
            if layout.views:
                out[d.id] = layout
                d.shown = list(dict.fromkeys(d.shown + [e for e in layout.elements() if e in ix.elements]))
            ph.advance()
    return out


def _svg(ix: ModelIndex, graph, title: str) -> bytes | None:
    svg = sketch_svg.render_svg(ix, graph, title)
    return svg.encode("utf-8") if svg else None


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


def ingest_project(content: ContentInfo, project: Project, root: Path, llm: EnrichmentSession, render: bool = True,
                   progress: Progress = QUIET, concurrency: int = 1, image_pixels: int = IMAGE_PIXELS,
                   modules: tuple[int, int, int] = MODULES) -> ProjectResult:
    """Parse, draw the sketches, ask the LLM (`enrich`), write."""
    ix = parse_project(project, progress)
    annotations: dict[str, list[Annotation]] = {}
    base = Trace(content_sha256=content.sha256)
    layouts = load_layouts(project, ix, progress)
    writer = ProjectWriter(content, project, ix, root, annotations, layouts, modules)
    enricher = Enricher(llm, writer.view, writer.plan, root, image_pixels)

    reused = 0  # sketches drawn by an interrupted attempt with the same tool and options
    if render and layouts:
        with progress.phase(f"{project.display_name}: rendering", len(layouts), "diagram") as ph:
            for dia_id in layouts:
                ph.advance()
                d = ix.diagrams[dia_id]
                el = ix.elements[dia_id]
                graph = writer.view.graph(dia_id)
                part = writer.view.partition(dia_id)  # a large diagram: an overview and a view per module (plan DV)
                title = f"{d.diagram_type or 'Diagram'}: {ix.qualified_name(dia_id)}"
                rel = writer.plan.dia_file[dia_id].removesuffix(".md") + ".png"
                reused += (root / rel).exists()
                if part is not None:
                    drawn = _draw(root / rel, partial(sketch.overview_png, ix, part, title, image_pixels))
                else:
                    drawn = _draw(root / rel, partial(sketch.render_png, ix, graph, title, pixels=image_pixels))
                if not drawn:
                    continue
                _draw(root / (rel.removesuffix(".png") + ".svg"), partial(_svg, ix, graph, title))  # for people (KX)
                tr = writer.view.trace(el).with_(entry=d.streams[0] if d.streams else el.entry, line=None,
                                            derivation=Derivation(method="rendered", inputs=tuple(d.streams)))
                label = f"Diagram sketch with its modules outlined ({SKETCH})" if part else f"Diagram sketch ({SKETCH})"
                annotations.setdefault(dia_id, []).append(Annotation(label, "", tr, image=rel))
                if part is None:
                    enricher.diagram(dia_id, tr, rel)
                    continue
                for m in part.modules:
                    mrel = writer.plan.module_image(dia_id, m.num)
                    if not _draw(root / mrel, partial(sketch.module_png, ix, part, m.num, title, image_pixels)):
                        continue
                    annotations[dia_id].append(
                        Annotation(f"Module M{m.num} sketch ({SKETCH})", "", tr, image=mrel, module=m.num))
                    enricher.module(dia_id, part, m.num, tr, mrel)
                enricher.large_diagram(dia_id, part, tr, rel)

    if reused:
        log.info("%s: reused %d sketch(es) drawn by an interrupted run", project.display_name, reused)

    # Embedded images (attachments, image shapes...). Linking them to elements depends on
    # version-specific storage, so they are listed at project level for now.
    images = []
    for entry in project.entry_names:
        if entry in project.model_entries or project.size(entry) < 64:
            continue
        with project.open(entry) as f:
            mime = image_mime(f.read(8))
        if not mime:
            continue
        rel = f"images/{slug(PurePosixPath(entry).name, 100)}.{mime.split('/')[1]}"
        writer.root.joinpath(rel).parent.mkdir(parents=True, exist_ok=True)
        writer.root.joinpath(rel).write_bytes(project.read(entry))
        tr = base.with_(entry=entry)
        images.append((entry, rel, tr))
        enricher.image(entry, rel, mime, tr)

    enricher.packages()
    if enricher.truncated:
        log.warning("%s: %d LLM input(s) were cut short to fit the prompt (element sections over %s characters, "
                    "diagrams over %d shapes or connections)", project.display_name, enricher.truncated,
                    f"{PART_CHARS[1]:,}", DIAGRAM_ITEMS)
    enricher.run(progress, project.display_name, concurrency)

    writer.pages.write_images(images, enricher.images, base)
    with progress.phase(f"{project.display_name}: writing", writer.write_steps(), "step") as ph:
        writer.write_all(tick=ph.advance)

    summary = {
        "name": content.name,
        "model_entries": project.model_entries,
        "exporter": ix.exporter,
        "elements": len(ix.elements),
        "diagrams": len(ix.diagrams),
        "stereotype_applications": len(ix.stereotypes),
        "relationships": len(writer.view.rels),
        "requirements": sum(1 for e in ix.elements.values() if sem.is_requirement(ix, e)),
        "images": len(images),
    }
    return ProjectResult(summary)

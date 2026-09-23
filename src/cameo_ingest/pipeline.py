"""Per-project pipeline: parse -> (render) -> (enrich) -> emit."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import diagrams as dg
from . import semantics as sem
from .archive import Project
from .emit import Annotation, Outputs, ProjectWriter, slug
from .layout import Layout, parse_layout
from .llm import LLM
from .model import ModelIndex
from .provenance import Derivation, RunInfo, Trace
from .xmi import finalize, parse_into

log = logging.getLogger(__name__)

IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}
MIN_SECTIONS_FOR_SUMMARY = 5
SUMMARY_INPUT_CHARS = 12000

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


def parse_project(project: Project) -> ModelIndex:
    ix = ModelIndex()
    for entry in project.model_entries:
        with project.open(entry) as f:
            parse_into(ix, f, entry)
    finalize(ix)
    return ix


def load_layouts(project: Project, ix: ModelIndex) -> dict[str, Layout]:
    """Parse each diagram's layout stream; record which elements it shows."""
    names = set(project.entry_names)
    out: dict[str, Layout] = {}
    for d in ix.diagrams.values():
        streams = [s for s in d.streams if s in names]
        if not streams:
            continue
        layout = Layout()
        for s in streams:
            with project.open(s) as f:
                head = f.read(64)
            if b"mdOwnedViews" not in head:
                continue  # an attachment stream, not a layout
            try:
                with project.open(s) as f:
                    layout.views += parse_layout(f).views
            except Exception as e:  # malformed stream: keep going
                log.warning("diagram %s: cannot parse layout %s: %s", d.id, s, e)
        if layout.views:
            out[d.id] = layout
            d.shown = list(dict.fromkeys(d.shown + [e for e in layout.elements() if e in ix.elements]))
    return out


def _image_mime(head: bytes) -> str | None:
    for magic, mime in IMAGE_MAGIC.items():
        if head.startswith(magic):
            return mime
    return None


def ingest_project(run: RunInfo, project: Project, root: Path, llm: LLM, render: bool = True) -> ProjectResult:
    ix = parse_project(project)
    annotations: dict[str, list[Annotation]] = {}
    base = Trace(source_sha256=run.source.sha256, container=project.trace_container)
    layouts = load_layouts(project, ix)
    writer = ProjectWriter(run, project, ix, root, annotations, layouts)

    for dia_id, layout in layouts.items() if render else ():
        d = ix.diagrams[dia_id]
        el = ix.elements[dia_id]
        png = dg.render_png(ix, layout, f"{d.diagram_type or 'Diagram'}: {ix.qualified_name(dia_id)}")
        if png is None:
            continue
        rel = writer.dia_file[dia_id].replace(".md", ".png")
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(png)
        writer.out.files.append(root / rel)
        tr = writer.trace(el).with_(entry=d.streams[0] if d.streams else el.entry, line=None,
                                    derivation=Derivation(method="rendered", inputs=tuple(d.streams)))
        annotations.setdefault(dia_id, []).append(
            Annotation("Diagram sketch (re-drawn from layout data, not a Cameo rendering)", "", tr, image=rel))
        if llm.cfg.vision_model:
            nodes, edges = dg.describe(ix, layout, lambda e: ix.label(e))
            context = "\n".join([f"Diagram: {d.name} ({d.diagram_type})", "Shapes:"] + nodes[:150]
                                 + ["Connections:"] + edges[:150])
            res = llm.describe_image(DIAGRAM_PROMPT + "\n\n" + context, png, "image/png",
                                     inputs=(writer.trace(el).locator(), tr.locator()))
            if res:
                text, deriv = res
                annotations[dia_id].append(Annotation("Diagram description", text, tr.with_(derivation=deriv)))

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
        data = project.read(entry)
        rel = f"images/{slug(PurePosixPath(entry).name, 100)}.{mime.split('/')[1]}"
        writer.root.joinpath(rel).parent.mkdir(parents=True, exist_ok=True)
        writer.root.joinpath(rel).write_bytes(data)
        writer.out.files.append(writer.root / rel)
        tr = base.with_(entry=entry)
        desc = llm.describe_image(IMAGE_PROMPT, data, mime, inputs=(tr.locator(),)) if llm.cfg.vision_model else None
        image_notes.append((entry, rel, tr, desc))

    # Package summaries from the deterministic text, so the LLM only rephrases what is there.
    if llm.cfg.text_model:
        for pkg_id, rel in writer.pkg_file.items():
            pkg = ix.elements[pkg_id]
            sections = writer._section_elements_in(pkg)
            if len(sections) < MIN_SECTIONS_FOR_SUMMARY:
                continue
            text = writer.section(pkg, rel, 1) + "\n".join(writer.section(e, rel, 2) for e in sections)
            tr = writer.trace(pkg)
            res = llm.summarize(PACKAGE_SUMMARY_PROMPT, text[:SUMMARY_INPUT_CHARS], inputs=(tr.locator(),))
            if res:
                summary, deriv = res
                annotations.setdefault(pkg_id, []).append(
                    Annotation("Summary", summary, tr.with_(derivation=deriv)))

    out = writer.write_all()
    if image_notes:
        lines = ["# Embedded images", ""]
        for entry, rel, tr, desc in image_notes:
            lines += [f"## {entry}", "", f"![{entry}]({rel})", ""]
            if desc:
                text, deriv = desc
                lines += [f"**Description** _(generated by {deriv.model}; not part of the source model)_:",
                          "", text, ""]
                writer.chunk(kind="image", title=f"Embedded image {entry}", text=text, file="images.md",
                             el=None, trace=tr.with_(derivation=deriv))
            lines += [f"<sub>trace: `{tr.locator()}`</sub>", ""]
        writer.write_text("images.md", "\n".join(lines))
        writer.write_indices()  # refresh chunks.jsonl with the image chunks

    summary = {
        "name": project.name,
        "container": list(project.trace_container),
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


"""A project's pages: a page per package (its sections) and per diagram, the README and the
embedded images (plan RA-13, AR-007R1)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from . import cameo_tables as ct
from . import crossref, hierarchies
from . import diagram_text as dt
from . import sections as sx
from . import semantics as sem
from .annotations import Annotation
from .external import library_name
from .files import FilePlan, relpath
from .model import Element
from .partition import Partition
from .provenance import Derivation, Trace, generated_by
from .sink import ChunkSink
from .text import front_matter, md_inline, plural, tidy
from .view import ProjectView


class PageWriter:
    def __init__(self, view: ProjectView, plan: FilePlan, sink: ChunkSink, root: Path):
        self.view, self.plan, self.sink, self.root = view, plan, sink, root

    # -- writing ---------------------------------------------------------------
    def write_text(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    # -- element sections ------------------------------------------------------
    def section(self, el: Element, from_file: str, level: int, generated: bool = True, trace: bool = True) -> str:
        """Markdown for one element. `generated=False` omits LLM-derived annotations, so
        chunks of extracted text keep a pure `extracted` provenance. `trace=False` omits the
        trace line, whose locator depends on where the source was found, not on what it says."""
        lines = self.view.section_view(el, generated, from_file).markdown(level, self.plan.linker(from_file))
        if trace:
            lines += [f"<sub>trace: `{self.view.trace(el).locator()}`</sub>", ""]
        return "\n".join(lines)

    def annotation_md(self, a: Annotation, from_file: str) -> list[str]:
        out = []
        if a.image:
            out += [f"![{a.label}]({relpath(a.image, from_file)})", ""]
        if a.text:
            out += [f"**{a.label}** _({generated_by(a.trace.derivation)})_:", "", tidy(a.text), ""]
        return out

    def write_images(self, images: list[tuple[str, str, Trace]], described: dict[str, tuple[str, Derivation]],
                     base: Trace) -> None:
        """images.md: the images embedded in the model (archive entry, file, trace), with their
        descriptions, each also a chunk."""
        if not images:
            return
        lines = ["# Embedded images", ""]
        for entry, rel, tr in images:
            lines += [f"## {entry}", "", f"![{entry}]({rel})", ""]
            if entry in described:
                text, deriv = described[entry]
                lines += [f"**Description** _({generated_by(deriv)})_:", "", text, ""]
                labelled = f"Description of embedded image {entry} ({generated_by(deriv)})\n\n{text}"
                self.sink.chunk(kind="generated:image_description", title=f"Image description: {entry}",
                           text=labelled, file="images.md", el=None, trace=tr.with_(derivation=deriv), salt=entry)
            lines += [f"<sub>trace: `{tr.locator()}`</sub>", ""]
        fm = front_matter({"title": f"Embedded images in {self.view.content.name}", "kind": "images",
                           "provenance": self.view.file_provenance(trace=base.to_dict())})
        self.write_text("images.md", fm + "\n".join(lines))

    # -- files -----------------------------------------------------------------
    def write_package(self, pkg: Element, rel: str) -> None:
        ix = self.view.ix
        qn = ix.qualified_name(pkg.id) or pkg.name or pkg.id
        body = [self.section(pkg, rel, 1)]
        body += self.part_sections(pkg, rel)
        subs = [c for c in sem.children(ix, pkg) if c.kind in sem.PACKAGE_KINDS]
        if subs:
            body.append("## Sub-packages\n")
            body += [f"- {self.plan.link(s.id, rel)}" for s in subs]
            body.append("")
        dias = [c for c in sem.children(ix, pkg) if c.kind == "Diagram"]
        if dias:
            body.append("## Diagrams\n")
            body += [f"- {self.plan.link(d.id, rel)}" for d in dias]
            body.append("")
        pkg_trace = self.view.trace(pkg)
        self.sink.section_chunks("package", pkg, self.view.section_view(pkg, generated=False), rel, pkg_trace,
                            heading=self.view.heading(pkg, "Package"), extra={"title": f"Package {qn}"})
        self.sink.generated_chunks(pkg, rel, "Package")
        # Every non-package section element whose nearest package is this one.
        for el in self.view.sections_in(pkg):
            body += [f'<a id="{self.plan.anchor(el)}"></a>\n', self.section(el, rel, 2)]
            anchor = f"{rel}#{self.plan.anchor(el)}"
            self.sink.section_chunks("requirement" if sem.is_requirement(ix, el) else "element", el,
                                self.view.section_view(el, generated=False), anchor, self.view.trace(el))
            self.sink.generated_chunks(el, anchor)
        fm = front_matter({
            "title": f"Package {qn}",
            "kind": "package",
            "element_id": pkg.id,
            "qualified_name": qn,
            "provenance": self.view.file_provenance(trace=pkg_trace.to_dict()),
        })
        self.write_text(rel, fm + "\n".join(body))

    def part_sections(self, pkg: Element, rel: str) -> list[str]:
        """A large package's parts, as summarized (FU-005, plan DV-05): the elements of each,
        its summary, and the summaries of runs of parts, each also a chunk that names the
        elements it covers."""
        parts = self.view.package_parts.get(pkg.id)
        anns = [a for a in self.view.ann.get(pkg.id, []) if a.module is not None or a.parts is not None]
        if not parts or not anns:
            return []
        ix = self.view.ix
        what = f"Package {ix.qualified_name(pkg.id)}"
        lines = ["## Parts, summarized", "",
                 (f"The package is large, so its elements were summarized in {len(parts)} parts, and its summary "
                  "above was built from these (through runs of parts, when there are many)."), ""]
        for a in sorted(anns, key=lambda a: (a.parts is None, a.parts or (a.module, a.module))):  # runs, then parts
            first, last = a.parts or (a.module, a.module)  # type: ignore[assignment]
            ids = [e for part in parts[first - 1:last] for e in part]
            if a.parts is None:
                anchor, title = f"part-{first}", f"Part {first} of {len(parts)}"
                links = ", ".join(self.plan.link(e, rel) for e in ids[:25]) + (", ..." if len(ids) > 25 else "")
                lines += [f'<a id="{anchor}"></a>', "", f"**{title}** ({plural(len(ids), 'element')}: {links}):", ""]
            else:
                anchor, title = f"parts-{first}-{last}", f"Parts {first} to {last} of {len(parts)}"
                lines += [f'<a id="{anchor}"></a>', "", f"**{title}** ({plural(len(ids), 'element')}):", ""]
            lines += self.annotation_md(a, rel)
            if a.trace.derivation.method != "llm" or not a.text:
                continue
            heading = self.sink.generated_heading(a, pkg, "Package", title[0].lower() + title[1:],
                                             [sem.label(ix, e) for e in ids])
            covers = {"number": first, "last": last, "of": len(parts), "anchor": f"{rel}#{anchor}", "elements": ids}
            self.sink.chunk(kind="generated:module_summary", title=f"{title}: {what}", text=f"{heading}\n\n{a.text}",
                       file=rel, el=pkg, trace=a.trace, salt=anchor, extra={"covers": covers})
            lines += [f"<sub>trace: `{a.trace.locator()}`</sub>", ""]
        return lines

    def write_diagram(self, dia_id: str, rel: str) -> None:
        ix = self.view.ix
        d = ix.diagrams[dia_id]
        el = ix.elements[dia_id]
        qn = ix.qualified_name(dia_id)
        fields: list[tuple[str, sx.Line]] = [("Diagram type", sx.line(d.diagram_type or "unknown"))]
        if d.uml_type and d.uml_type != d.diagram_type:
            fields.append(("UML diagram kind", sx.line(d.uml_type)))
        if d.owner:
            fields.append(("Owner / context", sx.line(self.view.ref(d.owner))))
        fields.append(("Qualified name", sx.line(sx.Span(qn, "code"))))
        for app in ix.applications(dia_id, sem.DIAGRAM_INFO):  # author and dates
            for k, vals in app.tags.items():
                fields.append((k.replace("_", " "), sx.line(", ".join(vals))))
        blocks = []
        doc = sem.documentation(ix, el)
        if doc:
            blocks.append(sx.Block("Documentation", [sx.line(tidy(doc))]))
        layout = self.view.layouts.get(dia_id)
        graph = self.view.graph(dia_id)
        part = self.view.partition(dia_id)
        if graph is not None:
            where = (lambda n: f" (M{part.module_of[n.num]})") if part else None
            nodes, edges = dt.describe(ix, graph, self.plan.refs(rel), where=where)
            if part:
                blocks.append(sx.Block("Modules", [sx.line(
                    "the diagram is large, so its shapes are grouped into modules of connected shapes drawn close "
                    "together, each drawn and described on its own below. The legend gives each shape's module.")],
                    label=f"**Modules ({len(part.modules)}):**", form="inline"))
            shapes = f"Shapes ({len(nodes)}), numbered as in the sketch and indented by nesting"
            blocks.append(sx.Block(shapes, [sx.markdown_line(n) for n in nodes], form="list"))
            blocks.append(sx.Block("Connections", [sx.markdown_line(e) for e in edges], form="list",
                                   label=f"**Connections ({len(edges)}):**"))
        tbl = [sx.line(t) for t in self.view.table_config(el)]
        table = ct.computed_kind(d.diagram_type)  # a table, a matrix or a map
        computed = self.view.table(dia_id)
        if computed is not None:  # a table, computed as Cameo shows it (plan CT)
            blocks += self.table_blocks(computed)
        elif table:
            missing = ct.not_computed(ix, dia_id) if layout is None else None
            relates = ct.describe_matrix(ix, dia_id)  # a matrix: what it relates, in words (ADR-0025)
            if missing is not None:  # what isn't shown, and why: said, not guessed at (plan CT)
                follows = " What it relates follows." if relates else " Its configuration follows."
                blocks.append(sx.Block("Not computed", [sx.line(missing[1] + follows)]))
            if relates:
                blocks.append(sx.Block("Matrix", [sx.line(relates)]))
            else:
                blocks.append(sx.Block("Table / matrix configuration", tbl, form="list", label=(
                    "**Table / matrix configuration** (Cameo computes the rows and cells from it when it shows the "
                    "table):")))
        else:
            blocks.append(sx.Block("Stereotypes and tagged values", tbl, form="list"))
        if d.shown and layout is None and computed is None:
            shown = f"Elements shown when last saved ({len(d.shown)})" if table else f"Elements shown ({len(d.shown)})"
            blocks.append(sx.Block("Elements shown", [sx.line(
                f"- {ix.elements[e].kind} {' '.join(f'«{s}»' for s in ix.stereotype_names(e)) + ' ' if ix.stereotype_names(e) else ''}",
                self.view.ref(e)) for e in d.shown], form="list", label=f"**{shown}:**"))
        view = sx.Section(sx.line("Diagram: ", sx.name(d.name or dia_id)), fields, blocks)
        lines = view.markdown(1, self.plan.linker(rel))
        tr = self.view.trace(el)
        trace_line = [f"<sub>trace: `{tr.locator()}`</sub>", ""]
        self.sink.section_chunks("diagram", el, view, rel, tr,
                            heading=self.view.heading(el, self.view.diagram_kind(dia_id)),
                            extra={"title": f"Diagram {qn}", "diagram_type": d.diagram_type})
        self.sink.generated_chunks(el, rel, self.view.diagram_kind(dia_id))
        for a in self.view.ann.get(dia_id, []):
            if a.module is None:
                lines += self.annotation_md(a, rel)
        if part is not None and graph is not None:
            lines += self.module_sections(el, part, rel)
        text = "\n".join(lines + trace_line)
        fm = front_matter({
            "title": f"Diagram {d.name}",
            "kind": "diagram",
            "element_id": dia_id,
            "diagram_type": d.diagram_type,
            "qualified_name": qn,
            "provenance": self.view.file_provenance(trace=tr.to_dict(), layout_streams=d.streams),
        })
        self.write_text(rel, fm + text)

    def table_blocks(self, t: ct.Table) -> list[sx.Block]:
        """A computed table: what it shows, in a sentence or two, then its rows (plan CT)."""
        ix = self.view.ix
        about = [f"Columns: {', '.join(c.header for c in t.columns)}."]
        if t.sort:
            about.append(f"Sorted by {t.sort}.")
        if t.row_types:
            about.append(f"Row types: {', '.join(t.row_types)}.")
        if t.scope:
            about.append(f"Scope: {', '.join(ix.qualified_name(s) for s in t.scope)}.")
        about.append(f"Rows: {len(t.rows)}, as the table lists them.")
        if t.not_computed:
            about.append(f"Not computed here (Cameo computes them): {', '.join(t.not_computed)}.")

        def cell(values: list[ct.Value]) -> sx.Line:
            spans: list[sx.Span | str] = []
            for k, v in enumerate(values):
                spans += (["; "] if k else []) + [sx.ref(v.ref, v.text) if v.ref else sx.name(v.text)]
            return sx.line(*spans)

        return [sx.Block("Table", [sx.line(" ".join(about))]),
                sx.Block("Rows", [], label=f"**Rows ({len(t.rows)}):**", form="table", detail=True,
                         columns=[c.header for c in t.columns], rows=[[cell(c) for c in row] for row in t.cells])]

    def module_sections(self, el: Element, part: Partition, rel: str) -> list[str]:
        """A section per module of a large diagram: its sketch, description, legend and
        connections; and its description as a chunk that says where in the diagram it is."""
        ix = self.view.ix
        what = f"{el.kind} {ix.qualified_name(el.id)}"
        kind_word = self.view.diagram_kind(el.id)
        lines = []
        for m in part.modules:
            anchor = f"module-m{m.num}"
            title = f"Module M{m.num} of {len(part.modules)}"
            lines += [f'<a id="{anchor}"></a>', "", f"## {title}", ""]
            anns = [a for a in self.view.ann.get(el.id, []) if a.module == m.num]
            for a in anns:
                lines += self.annotation_md(a, rel)
            legend, inside, edge = dt.module_lists(ix, part, m.num, self.plan.refs(rel))
            lines += [f"**Shapes ({len(legend)}):**"] + legend + [""]
            if inside:
                lines += [f"**Connections within the module ({len(inside)}):**"] + inside + [""]
            if edge:
                lines += [f"**Connections with other modules ({len(edge)}):**"] + edge + [""]
            shapes = [n for n in part.graph.nodes if part.module_of[n.num] == m.num]
            where = {
                "number": m.num, "of": len(part.modules), "anchor": f"{rel}#{anchor}",
                "shapes": m.shapes, "elements": list(dict.fromkeys(
                    n.view.element for n in shapes if n.view.element and n.view.element in ix.elements)),
                "box": [round(v, 1) for v in m.box],
                "image": next((a.image for a in anns if a.image), None),
            }
            for a in anns:
                if a.trace.derivation.method != "llm" or not a.text:
                    continue
                heading = self.sink.generated_heading(a, el, kind_word, title.lower(), [n.label for n in shapes],
                                                 "showing")
                self.sink.chunk(kind="generated:module_description", title=f"{title}: {what}",
                           text=f"{heading}\n\n{a.text}", file=rel, el=el, trace=a.trace, salt=f"M{m.num}",
                           extra={"covers": where})
                lines += [f"<sub>trace: `{a.trace.locator()}`</sub>", ""]
        return lines

    def write_threads(self, threads: list[dict[str, Any]]) -> None:
        """THREADS.md: the project's derivation trees, when it has any (plan RF-05)."""
        if threads:
            fm = front_matter({"title": f"Threads in {self.view.content.name}", "kind": "threads",
                               "provenance": self.view.file_provenance(trace=self.view.trace().to_dict())})
            self.write_text(crossref.THREADS, fm + crossref.threads_page(threads, self.view.content))

    def write_hierarchies(self, kinds: list[dict[str, Any]]) -> None:
        """HIERARCHIES.md: the project's type hierarchies, when it has any (plan TH)."""
        if kinds:
            fm = front_matter({"title": f"Hierarchies in {self.view.content.name}", "kind": "hierarchies",
                               "provenance": self.view.file_provenance(trace=self.view.trace().to_dict())})
            self.write_text(hierarchies.FILE, fm + hierarchies.hierarchies_page(kinds, self.view.content))

    def write_readme(self) -> None:
        ix = self.view.ix
        counts: dict[str, int] = defaultdict(int)
        for el in ix.elements.values():
            counts[el.kind] += 1
        st_counts: dict[str, int] = defaultdict(int)
        for a in ix.stereotypes.values():
            st_counts[a.name] += 1
        lines = [f"# Cameo project: {md_inline(self.view.content.name)}", ""]
        exp = ", ".join(f"{k}: {v}" for k, v in ix.exporter.items())
        lines += [(f"- **Content:** `{self.view.content.token}` (where this content was found is recorded under "
                   "this token, in `INDEX.md` and `provenance.jsonl` at the root of the output tree)"),
                  f"- **Exporter:** {exp or 'unknown'}",
                  (f"- **Elements:** {len(ix.elements)}; **diagrams:** {len(ix.diagrams)}; "
                   f"**relationships:** {len(self.view.rels)}; **stereotype applications:** {len(ix.stereotypes)}"),
                  ""]
        lines.append("## Top-level packages\n")
        for r in ix.roots:
            el = ix.elements[r]
            for c in [el] + sem.children(ix, el):
                if c.kind in sem.PACKAGE_KINDS:
                    lines.append(f"- {self.plan.link(c.id, 'README.md')}")
        lines.append("")
        if ix.diagrams:
            lines.append("## Diagrams\n")
            for d in sorted(ix.diagrams.values(), key=lambda d: ix.qualified_name(d.id)):
                lines.append(f"- {self.plan.link(d.id, 'README.md')} — {d.diagram_type or ''}")
            lines.append("")
        lines.append("## Element kinds\n")
        lines += [f"- {k}: {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1])]
        lines.append("")
        if st_counts:
            lines.append("## Stereotypes applied\n")
            lines += [f"- «{k}»: {n}" for k, n in sorted(st_counts.items(), key=lambda x: -x[1])]
            lines.append("")
        if ix.external_refs:
            bases = sorted({h.split("#", 1)[0] for h in ix.external_refs})
            libraries = {b: library_name(b) for b in bases if library_name(b)}
            lines.append("## Used projects and standard libraries\n")
            lines += [f"- Used project `{b}`" for b in bases if b not in libraries]
            lines += [f"- Standard library {name}: `{b}`" for b, name in libraries.items()]
            lines.append("")
        text = "\n".join(lines)
        tr = self.view.trace()
        # The chunk names the project by its label: file names can be long, and can repeat.
        chunk_text = text.replace(lines[0], f"# Cameo project: {md_inline(self.view.content.label)}", 1)
        self.sink.text_chunks(kind="project", title=f"Cameo project {self.view.content.name}", text=chunk_text,
                         file="README.md", el=None, trace=tr)
        fm = front_matter({"title": f"Cameo project {self.view.content.name}", "kind": "project",
                           "provenance": self.view.file_provenance(trace=tr.to_dict())})
        self.write_text("README.md", fm + text)

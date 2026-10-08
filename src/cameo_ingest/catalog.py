"""A project's catalog: one record per item worth finding by keyword, for the exports that people
search without tools (plan KX): the workbook and the search page.

`project_catalog` makes the records at build time, from the in-memory model, with the pages'
vocabulary (labels, kind words, requirement ids, relationship wording), into
`index/catalog.jsonl`. They are the only thing the exports read from a project (AR-012). In
order:
- `project`, once, first: what the project is, its counts, and the elements left out, by
  metaclass;
- `requirement`, `diagram`, `package`, `element`: the items in scope;
- `relationship`: every relationship, with both ends;
- `summary`: every generated text (LLM), with the model that wrote it.

In scope: requirements, diagrams, packages, and every other element that has a chunk of its own
or a name or documentation. An element without a chunk of its own (a part property, a port, a
pin) is `listed_in` the nearest owner that has one, and borrows its chunks.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import cameo_tables as ct
from . import semantics as sem
from .progress import QUIET, Progress
from .text import one_line, shown_value
from .treefiles import index_file, project_dir, read_jsonl

if TYPE_CHECKING:
    from .sink import ChunkSink
    from .state import State
    from .view import ProjectView

SECTION_KINDS = ("element", "requirement", "package", "diagram")
OUT_OF_SCOPE = {"Comment"}  # documentation, which its owner's record holds


def project_catalog(  # noqa: C901 (CQ-024: to be split)
        view: ProjectView, sink: ChunkSink, root: Path | None = None) -> Iterator[dict[str, Any]]:
    """The project's records; `root`, the project's directory, to find its SVG sketches."""
    ix = view.ix
    chunks_of: dict[str, list[str]] = defaultdict(list)  # element -> its section chunks, main first
    for c in sink.chunks:
        m = c["metadata"]
        if m.get("element_id") and m["kind"].split(":")[0] in SECTION_KINDS and not m["kind"].startswith("generated"):
            chunks_of[m["element_id"]].append(c["id"])

    def tagged_values(key: str) -> dict[str, str]:
        """Its stereotypes' tagged values as people set them (plan SH, D2): "Stereotype.tag" to the
        values, references by their targets' labels. Not DiagramInfo's (authors and dates, which the
        tool keeps), nor a requirement's Id and Text, which are fields of their own."""
        out = {}
        for app in ix.applications(key):
            if app.name == sem.DIAGRAM_INFO:
                continue
            for tag, values in sorted(app.tags.items()):
                if sem.is_requirement(ix, ix.elements[key]) and tag in ("Id", "Text"):
                    continue
                shown = [one_line(ix.label(v)) if ix.refers(v) else shown_value(v) for v in values]
                if any(shown):
                    out[f"{app.name}.{tag}"] = "; ".join(shown)
        return out

    def label(key: str) -> str:
        return one_line(sem.label(ix, key))

    def ref(key: str) -> list[str]:
        return [key, label(key)]

    def relations(el_id: str) -> list[list[str]]:
        out = []
        for r in view.rels_by_end.get(el_id, []):
            w = sem.wording(r.kind, r.metaclass)
            if r.source == el_id:
                out.append([r.id, r.kind, "out", w.forward if w else f"{r.kind} →", *ref(r.target)])
            if r.target == el_id:
                out.append([r.id, r.kind, "in", w.inverse if w else f"{r.kind} ←", *ref(r.source)])
        return out

    def listed_in(el_id: str) -> str | None:
        owner = ix.elements[el_id].owner
        while owner and owner not in chunks_of:
            owner = ix.elements[owner].owner if owner in ix.elements else None
        return owner

    records: list[dict[str, Any]] = []
    left_out: Counter[str] = Counter()
    tables: Counter[str] = Counter()  # tables, matrices and maps: computed, or why not (plan CT)
    for el in ix.elements.values():
        if el.kind in sem.RELATIONSHIP_KINDS or el.kind in OUT_OF_SCOPE:
            continue
        rq = sem.requirement(ix, el)
        doc = sem.documentation(ix, el)
        if el.id in ix.diagrams:
            d = ix.diagrams[el.id]
            rec: dict[str, Any] = {"type": "diagram", "kind": d.diagram_type or "Diagram",
                                   "owner": ref(d.owner) if d.owner else None, "shapes": len(d.shown)}
            if (t := view.table(el.id)) is not None:
                rec["table"] = f"{len(t.rows)} rows"
                tables["computed"] += 1
            elif el.id not in view.layouts and (why := ct.not_computed(ix, el.id)) is not None:
                rec["table"] = f"not computed: {why[0]}"
                tables["not computed"] += 1
            if (g := view.graph(el.id)) is not None:  # its number tags, for links at "[n]" in its text (TR-005)
                tags = {str(n.num): n.view.element for n in g.nodes if n.view.element}
                if tags:
                    rec["tags"] = tags
            images = [a for a in view.ann.get(el.id, []) if a.image]
            for a in images:  # its sketch, and a large diagram's modules (plan KX-05)
                if a.module is None:
                    rec["sketch"] = a.image
                    svg = a.image.removesuffix(".png") + ".svg"
                    if root is not None and (root / svg).is_file():
                        rec["svg"] = svg
                else:
                    rec.setdefault("modules", []).append(a.image)
        elif el.kind in sem.PACKAGE_KINDS:
            rec = {"type": "package", "kind": el.kind}
        elif rq is not None:
            rec = {"type": "requirement", "kind": "Requirement", "id": rq.id, "db": rq.db_id, "text": rq.text}
        elif el.id in chunks_of or (el.name or "").strip() or doc:
            rec = {"type": "element", "kind": sem.kind_word(ix, el)}
        else:
            left_out[el.kind] += 1
            continue
        pkg = view.package_of(el)
        rec = {"key": el.id, **rec, "name": label(el.id), "where": ix.qualified_name(el.id),
               "package": ix.qualified_name(pkg.id) if pkg else "", "stereotypes": ix.stereotype_names(el.id)}
        if doc:
            rec["text"] = (rec.get("text", "") + "\n\n" + doc).strip() if rec.get("text") else doc
        rec["relations"] = relations(el.id)
        if tagged := tagged_values(el.id):
            rec["tagged"] = tagged
        rec["diagrams"] = [ref(d) for d in view.diagrams_showing.get(el.id, []) if d != el.id]
        if el.id in chunks_of:
            rec["chunks"] = chunks_of[el.id]
        elif (owner := listed_in(el.id)) is not None:
            rec["listed_in"] = ref(owner)
            rec["chunks"] = chunks_of[owner]
        records.append(rec)
    rels = [{"type": "relationship", "key": r.id, "kind": r.kind, "source": ref(r.source), "target": ref(r.target),
             "phrase": (w.forward if (w := sem.wording(r.kind, r.metaclass)) else f"{r.kind} →")}
            for r in view.rels if r.source in ix.elements and r.target in ix.elements]
    summaries = []
    for el_id, anns in view.ann.items():
        for a in anns:
            if a.trace.derivation.method != "llm" or not a.text:
                continue
            rec = {"type": "summary", "key": el_id, "of": ref(el_id), "label": a.label, "text": a.text,
                   "model": a.trace.derivation.model}
            if a.module is not None:
                rec["module"] = a.module
            if a.parts is not None:
                rec["parts"] = list(a.parts)
            summaries.append(rec)
    counts = Counter(r["type"] for r in records + rels + summaries)
    yield {"type": "project", "name": view.content.name, "label": view.content.label, "token": view.content.token,
           "saved_by": ix.exporter, "counts": dict(sorted(counts.items())), "left_out": dict(sorted(left_out.items())),
           "tables": dict(sorted(tables.items()))}
    yield from records
    yield from rels
    yield from summaries


# -- reading a tree's catalogs, for the exports ----------------------------------------------------
@dataclass
class ProjectCatalog:
    """One project's records, with what the tree knows about it: its identifiers
    (`index/ids.jsonl`) and where its model was found (paths and `--meta` values)."""

    header: dict[str, Any]
    records: list[dict[str, Any]]
    ids: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)  # [{"path", "metadata"}]
    chunks: dict[str, str] = field(default_factory=dict)  # chunk id -> text, when asked for
    dir: Path | None = None  # the project's directory in the tree, for its sketches

    @property
    def label(self) -> str:
        return self.header["label"]

    def source_text(self) -> str:
        return "; ".join(s["path"] for s in self.sources)

    def metadata_text(self) -> str:
        return "; ".join(dict.fromkeys(f"{k}={v}" for s in self.sources for k, v in sorted(s["metadata"].items())))


def tree_catalogs(state: State, out: Path, missing: list[str], progress: Progress | None = None,
                  chunks: bool = False) -> Iterator[ProjectCatalog]:
    """The written projects' catalogs, one at a time, with their chunks' text if `chunks`. A
    project made before catalogs existed (0.8.0) is named in `missing`: `run` makes it again."""
    rows = state.written()
    with (progress or QUIET).phase("projects", len(rows), "project") as ph:
        for row in rows:
            ph.advance()
            d = project_dir(out, row["content_sha256"])
            path = index_file(d, "catalog")
            if not path.is_file():
                missing.append(row["name"])
                continue
            recs = read_jsonl(path)
            ids = read_jsonl(index_file(d, "ids"), missing_ok=True)
            sources = [{"path": "!".join([s["path"], *json.loads(s["chain"])]), "metadata": json.loads(s["metadata"])}
                       for s in state.sightings(row["content_sha256"]) if s["input_status"] != "missing"]
            texts = {c["id"]: c["text"] for c in read_jsonl(index_file(d, "chunks"))} if chunks else {}
            yield ProjectCatalog(recs[0], recs[1:], ids, sources, texts, d)


@dataclass
class ExportInputs:
    """What the workbook and the search page show beside the projects' catalogs (CQ-006): made once
    for both, so that they agree."""

    subjects: dict[str, Any] | None = None  # the tree's subjects.json (ADR-0031)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)  # by token: `lineage.facts` (plan LN-06)
    links: dict[tuple[str, str], list[Any]] = field(default_factory=dict)  # by (token, key): `shared.find` (plan SH)
    labels: dict[str, str] = field(default_factory=dict)  # by token: each written project's label

    def label(self, token: str) -> str:
        return self.labels.get(token, token[7:15])


def export_inputs(state: State, out: Path) -> ExportInputs:
    """The tree's subjects, each written model's lineage facts and label, and its items' copies in
    other models; the catalogs are read twice for the copies, as `shared.find` needs."""
    from . import discovery, lineage, shared
    from .provenance import ContentInfo

    facts = lineage.facts(state)
    links = shared.find(lambda: tree_catalogs(state, out, [], QUIET), shared.related_by(facts))
    labels = {f"sha256:{r['content_sha256']}": ContentInfo(r["content_sha256"], r["name"]).label
              for r in state.written()}
    return ExportInputs(discovery.read(out), facts, links, labels)


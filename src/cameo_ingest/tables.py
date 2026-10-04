"""A project's tables (CSV) and indices (JSON Lines): elements, relationships, requirements,
properties, tagged values, diagrams; the element index, the hierarchy and the chunks (plan RA-13,
AR-007R1)."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import cameo_tables as ct
from . import catalog, crossref
from . import semantics as sem
from .files import FilePlan
from .sink import ChunkSink
from .view import ProjectView


class TableWriter:
    def __init__(self, view: ProjectView, plan: FilePlan, sink: ChunkSink, root: Path):
        self.view, self.plan, self.sink, self.root = view, plan, sink, root

    # -- tables & indices ------------------------------------------------------
    def write_csv(self, rel: str, header: list[str], rows: list[list[Any]]) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    def write_tables(self) -> None:
        ix = self.view.ix
        rows = []
        for el in ix.elements.values():
            rows.append([el.id, el.type, el.name or "", ix.qualified_name(el.id), el.owner or "",
                         ";".join(ix.stereotype_names(el.id)), sem.documentation(ix, el),
                         self.plan.file_of.get(el.id, ""), self.view.trace(el).locator()])
        self.write_csv("tables/elements.csv", ["id", "type", "name", "qualified_name", "owner_id",
                                                "stereotypes", "documentation", "file", "trace"], rows)
        rows = []
        for r in self.view.rels:
            el = ix.elements[r.id]
            rows.append([r.id, r.kind, r.metaclass, r.name or "", r.source, ix.qualified_name(r.source) or r.source,
                         r.target, ix.qualified_name(r.target) or r.target, self.view.trace(el).locator()])
        self.write_csv("tables/relationships.csv", ["id", "kind", "metaclass", "name", "source_id", "source",
                                                     "target_id", "target", "trace"], rows)
        rows = []
        for el in ix.elements.values():
            if not sem.is_requirement(ix, el):
                continue
            f = sem.requirement_fields(ix, el)
            rel_by_kind: dict[str, list[str]] = defaultdict(list)
            for r in self.view.rels_by_end.get(el.id, []):
                other = r.source if r.target == el.id else r.target
                direction = "in" if r.target == el.id else "out"
                rel_by_kind[f"{r.kind}_{direction}"].append(ix.qualified_name(other) or other)
            rows.append([el.id, f.get("Id", ""), el.name or "", f.get("Text", ""), ix.qualified_name(el.id),
                         ";".join(ix.stereotype_names(el.id)),
                         json.dumps(rel_by_kind, ensure_ascii=False) if rel_by_kind else "",
                         self.plan.file_of.get(el.id, ""), self.view.trace(el).locator()])
        self.write_csv("tables/requirements.csv", ["id", "req_id", "name", "text", "qualified_name",
                                                    "stereotypes", "relationships", "file", "trace"], rows)
        rows = []
        for el in ix.elements.values():
            if el.role not in ("ownedAttribute", "ownedPort", "ownedEnd"):
                continue
            t = sem.refs(el, "type")
            rows.append([el.id, el.owner or "", ix.qualified_name(el.owner) if el.owner else "", el.name or "",
                         el.kind, ";".join(ix.stereotype_names(el.id)),
                         ix.qualified_name(t[0]) if t and t[0] in ix.elements else (t[0] if t else ""),
                         sem.multiplicity(ix, el) or "", el.attrs.get("aggregation", ""),
                         sem.value_text(ix, next(iter(sem.children(ix, el, "defaultValue")), None)) or "",
                         self.view.trace(el).locator()])
        self.write_csv("tables/properties.csv", ["id", "owner_id", "owner", "name", "kind", "stereotypes", "type",
                                                  "multiplicity", "aggregation", "default", "trace"], rows)
        rows = []
        for app in ix.stereotypes.values():
            base = ix.elements.get(app.base)
            tr = self.view.trace(base).with_(line=app.line) if base else self.view.trace().with_(xmi_id=app.id, line=app.line,
                                                                                         entry=app.entry)
            for k, vals in app.tags.items():
                for v in vals:
                    rows.append([app.base, ix.qualified_name(app.base) if base else "", app.stereotype, k,
                                 ix.qualified_name(v) if v in ix.elements else v, tr.locator()])
        self.write_csv("tables/tagged_values.csv", ["element_id", "element", "stereotype", "tag", "value", "trace"],
                       rows)
        rows = []
        for d in ix.diagrams.values():
            rows.append([d.id, d.name, d.diagram_type or "", d.uml_type or "",
                         ix.qualified_name(d.owner) if d.owner else "", len(d.shown), self.plan.dia_file.get(d.id, ""),
                         self.view.trace(ix.elements[d.id]).locator()])
        self.write_csv("tables/diagrams.csv", ["id", "name", "diagram_type", "uml_type", "owner", "elements_shown",
                                                "file", "trace"], rows)
        for d in ix.diagrams.values():  # each computed table as Cameo shows it, cells whole (plan CT)
            t = self.view.table(d.id)
            if t is None or d.id not in self.plan.dia_file:
                continue
            stem = Path(self.plan.dia_file[d.id]).stem
            self.write_csv(f"tables/diagram-tables/{stem}.csv", [c.header for c in t.columns] + ["id", "trace"],
                           [[ct.text_of(c) for c in cells] + [r, self.view.trace(ix.elements[r]).locator()]
                            for r, cells in zip(t.rows, t.cells, strict=True)])

    def write_indices(self, threads: list[dict[str, Any]]) -> None:
        ix = self.view.ix
        p = self.root / "index/threads.jsonl"  # derivation trees, which the tree's chunks include or not
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for t in threads:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        p = self.root / "index/ids.jsonl"  # identifiers, for the index across models (AR-012R1)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for rec in crossref.project_places(self.view, self.sink.main):
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        p = self.root / "index/catalog.jsonl"  # what the exports search (plan KX-02)
        with p.open("w", encoding="utf-8") as f:
            for rec in catalog.project_catalog(self.view, self.sink, self.root):
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        p = self.root / "index/elements.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for el in ix.elements.values():
                rec = {
                    "id": el.id, "type": el.type, "role": el.role, "name": el.name, "owner": el.owner,
                    "qualified_name": ix.qualified_name(el.id), "attrs": el.attrs,
                    "refs": [[r, t] for r, t in el.refs], "children": el.children,
                    "stereotypes": [{"name": a.stereotype, "tags": a.tags} for a in ix.applications(el.id)],
                    "file": self.plan.file_of.get(el.id), "provenance": self.view.trace(el).to_dict(),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        def tree(eid: str, seen: set[str]) -> dict[str, Any] | None:
            el = ix.elements.get(eid)
            if el is None or eid in seen:
                return None
            seen.add(eid)
            kids = [t for c in el.children if (t := tree(c, seen))]
            if not (sem.is_section(ix, el) or kids):
                return None
            node: dict[str, Any] = {"id": eid, "name": el.name, "kind": el.kind}
            if st := ix.stereotype_names(eid):
                node["stereotypes"] = st
            if eid in self.plan.file_of:
                node["file"] = self.plan.file_of[eid]
            if kids:
                node["children"] = kids
            return node

        seen: set[str] = set()
        h = {"project": self.view.content.name, "provenance": self.view.file_provenance(),
             "roots": [t for r in ix.roots if (t := tree(r, seen))]}
        p = self.root / "index/hierarchy.json"
        p.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
        p = self.root / "index/chunks.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for c in self.sink.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

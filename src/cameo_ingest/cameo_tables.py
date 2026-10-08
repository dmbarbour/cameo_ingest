"""Cameo's tables (plan CT): a table's columns, rows and cells, computed as Cameo computes them
whenever it shows the table. The file stores a table's configuration as tags of a stereotype on
its diagram (`DiagramTable`, `InstanceTable`, `RequirementTable`, ...), and usually its rows; it
never stores the cells.

- **Columns:** `columnIds`, but those in `hideColumns`, in order. A column reads a row's
  property (`QPROP:Element:name`), a tag of a stereotype (`QPROP:stereotypeTags:<<P::S>>.tag`),
  or, in an instance table, an attribute's slot (`IColumn:<feature id>`). Columns defined by
  expressions (`CUSTOM_COLUMN:`), and properties derived by a profile, are Cameo's to compute:
  they keep their header, and are listed as not computed.
- **Rows:** `rowElements`, then `additionalElements`: the elements the table lists. In the
  samples they are exactly the rows Cameo saved (`usedObjects`) for 120 of 122 tables.
- **Order:** `sort` (`QPROP:Element:Id^Asc`), with numbers in text compared as numbers.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from . import semantics as sem
from .model import Element, ModelIndex
from .richtext import to_text
from .text import natural_key, shown_value

NUMBER = "_NUMBER_"
# Derived properties that read a relationship: (the relationship's kind, the row at its source).
RELATION_PROPERTIES = {
    "satisfies": ("satisfy", True), "satisfiedby": ("satisfy", False),
    "refines": ("refine", True), "refinedby": ("refine", False),
    "verifies": ("verify", True), "verifiedby": ("verify", False),
    "tracedto": ("trace", True), "tracedfrom": ("trace", False),
    "derivedfrom": ("derivereqt", True), "derived": ("derivereqt", False), "derivedto": ("derivereqt", False),
    "allocatedto": ("allocate", True), "allocatedfrom": ("allocate", False),
    "master": ("copy", True), "copies": ("copy", False),
}
ALIASES = {"name0": "name", "documentation0": "documentation"}  # a glossary table's columns


@dataclass(frozen=True)
class Value:
    """A cell's value: text, or an element (`ref`), labelled."""

    text: str
    ref: str | None = None


Cell = list[Value]


@dataclass
class Column:
    id: str  # as Cameo names it: "QPROP:Element:Id"
    header: str
    read: Callable[[Element], Cell] | None  # None: Cameo computes it, not we


@dataclass
class Table:
    columns: list[Column]
    rows: list[str]  # element ids, in the table's order
    cells: list[list[Cell]]  # by row, then by column; a NUMBER column holds the row's number
    sort: str = ""  # "Id, ascending", as it reads
    row_types: list[str] = field(default_factory=list)  # labels
    scope: list[str] = field(default_factory=list)  # element ids

    @property
    def not_computed(self) -> list[str]:
        return [c.header for c in self.columns if c.read is None and c.id != NUMBER]


def is_table(diagram_type: str | None) -> bool:
    """A table, not a matrix or a map, by its diagram type."""
    t = diagram_type or ""
    return "Table" in t


def computed_kind(diagram_type: str | None) -> bool:
    """A table, a matrix or a map: what Cameo computes when it shows it."""
    t = diagram_type or ""
    return any(w in t for w in ("Table", "Matrix", "Map"))


def not_computed(ix: ModelIndex, dia_id: str) -> tuple[str, str] | None:
    """Why a table, matrix or map (without a layout) that `build` doesn't compute isn't: a short
    reason, and a sentence that says what is missing and why (plan CT). None for a diagram of
    another kind."""
    d = ix.diagrams.get(dia_id)
    if d is None or not computed_kind(d.diagram_type):
        return None
    if not is_table(d.diagram_type):
        what, parts = (("matrix", "rows, columns and cells") if "Matrix" in (d.diagram_type or "")
                       else ("map", "elements and connections"))
        return (f"a {what}", (f"Cameo computes what this {what} shows whenever it shows it, and the model file "
                              f"stores none of it, so its {parts} aren't shown here."))
    tags = configuration(ix, dia_id)
    if not tags.get("columnIds"):
        return ("no columns", "Its configuration names no columns, so its cells aren't shown here.")
    if any(x in ix.elements for k in ("rowElements", "additionalElements") for x in tags.get(k, [])):
        return None  # computed
    if [s for s in tags.get("scope", []) if s in ix.elements]:
        return ("rows from scope", ("Cameo finds this table's rows in its scope whenever it shows the table, and "
                                    "the model file doesn't store them, so its rows and cells aren't shown here."))
    return ("no rows", "The model file lists no rows for it, so its cells aren't shown here.")


EXPRESSIONS = "{http://www.nomagic.com/schemas/MagicDraw/StructuredExpression/2013}"
DIRECTIONS = {"Row to column": "from row to column", "Column to row": "from column to row", "Both": "either way"}


def _criterion(xml: str) -> str | None:
    """A dependency criterion's name, from Cameo's structured expression ("Allocate"), or None."""
    try:
        root = etree.fromstring(xml.encode())
    except etree.XMLSyntaxError:
        return None
    for entry in root.findall(f"{EXPRESSIONS}taggedValues/{EXPRESSIONS}entry"):
        if entry.get("key") == "name":
            return entry.findtext(f"{EXPRESSIONS}value")
    return None


def _axis(ix: ModelIndex, tags: dict[str, list[str]], axis: str) -> str:
    """What a matrix's rows (or columns) are, as its configuration says: element types, scope."""
    types = [sem.label(ix, t) for t in tags.get(f"{axis}ElementType", [])]
    what = ", ".join(types[:12]) + (f", and {len(types) - 12} more kinds" if len(types) > 12 else "") or "elements"
    scope = tags.get(f"{axis}Scope", [])
    if scope:
        inside = [ix.qualified_name(s) for s in scope if s in ix.elements]
        outside = [sem.label(ix, s) for s in scope if s not in ix.elements]
        where = "; ".join(inside + [f"{o} (outside this project)" for o in outside])
        what += f" in {where}"
    elif (tags.get("takeWholeModelAsScope") or ["false"])[0] == "true":
        what += " in the whole model"
    if tags.get(f"{axis}Query"):
        what += ", chosen by a query"
    removed = len(tags.get(f"removed{axis.capitalize()}Elements", []))
    if removed:
        what += f", {removed} removed by hand"
    return what


def describe_matrix(ix: ModelIndex, dia_id: str) -> str | None:
    """What a matrix relates, in words, from its configuration alone: its rows, its columns, what
    a cell marks and which way. Nothing is computed (ADR-0025)."""
    d = ix.diagrams.get(dia_id)
    if d is None or "Matrix" not in (d.diagram_type or ""):
        return None
    tags = configuration(ix, dia_id)
    criteria = list(dict.fromkeys(n for x in tags.get("dependencyCriteria", []) if (n := _criterion(x))))
    marks = (", ".join(criteria[:-1]) + " or " + criteria[-1] if len(criteria) > 1 else criteria[0]) if criteria \
        else "relations Cameo's criteria select"
    way = DIRECTIONS.get((tags.get("direction") or [""])[0], "")
    shown = (tags.get("showElements") or [""])[0]
    out = [f"Rows: {_axis(ix, tags, 'row')}.", f"Columns: {_axis(ix, tags, 'column')}.",
           f"A cell marks {marks}{', ' + way if way else ''}."]
    if shown == "With relations":
        out.append("Only rows and columns with a marked cell are shown.")
    elif shown == "All":
        out.append("All rows and columns are shown, marked or not.")
    return " ".join(out)


def configuration(ix: ModelIndex, dia_id: str) -> dict[str, list[str]]:
    """The tags of the diagram's stereotypes, but DiagramInfo's: a table's configuration."""
    out: dict[str, list[str]] = {}
    for app in ix.applications(dia_id):
        if app.name != sem.DIAGRAM_INFO:
            for k, vals in app.tags.items():
                out.setdefault(k, vals)
    return out


def _words(name: str) -> str:
    """A property's name as a header: "SatisfiedBy" → "Satisfied By", "hierarchyId" → "Hierarchy Id"."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return spaced[:1].upper() + spaced[1:]


def _values(ix: ModelIndex, vals: list[str]) -> Cell:
    """Tag or reference values: elements by label, text as shown on pages."""
    out = []
    for v in vals:
        if v in ix.elements or v in ix.external_refs:
            out.append(Value(sem.label(ix, v), v if v in ix.elements else None))
        else:
            out.append(Value(shown_value(to_text(v))))
    return out


def _once(cell: Cell) -> Cell:
    """Each value once: two stereotypes on an element can carry a tag of one name and value."""
    return list(dict.fromkeys(cell))


class Columns:
    """How each kind of column reads a row, over one model."""

    def __init__(self, ix: ModelIndex, rels: list[sem.Relationship]):
        self.ix = ix
        self.related: dict[tuple[str, str, bool], list[str]] = defaultdict(list)  # (element, kind, out) -> others
        for r in rels:
            k = r.kind.lower()
            self.related[(r.source, k, True)].append(r.target)
            self.related[(r.target, k, False)].append(r.source)

    def column(self, cid: str, rows: list[Element]) -> Column:
        ix = self.ix
        if cid == NUMBER:
            return Column(cid, "#", None)
        if cid.startswith("CUSTOM_COLUMN:"):
            return Column(cid, cid.split(":", 1)[1].strip(), None)
        if cid.startswith("IColumn:"):
            feature = cid.split(":", 1)[1]
            header = sem.label(ix, feature) if feature in ix.elements else "(attribute)"
            return Column(cid, header, (lambda el: self._slot(el, feature)) if feature in ix.elements else None)
        m = re.match(r"QPROP:stereotypeTags:<<(?:[^>]*::)?([^>]+)>>\.(.+)$", cid)
        if m:
            stereo, tag = m.groups()
            return Column(cid, tag, lambda el: _once([v for a in ix.applications(el.id) if a.name == stereo
                                                      for v in _values(ix, a.tags.get(tag, []))]))
        prop = ALIASES.get(cid, cid.split(":", 2)[2] if cid.startswith("QPROP:Element:") else "")
        if not prop:
            return Column(cid, cid, None)
        read = self._property(prop, rows)
        return Column(cid, _words(prop), read)

    def _property(self, prop: str, rows: list[Element]) -> Callable[[Element], Cell] | None:
        ix = self.ix
        simple: dict[str, Callable[[Element], Cell]] = {
            "name": lambda el: [Value(el.name or sem.label(ix, el.id), el.id)],
            "documentation": lambda el: [Value(to_text(sem.documentation(ix, el)))],
            "owner": lambda el: [Value(sem.label(ix, el.owner), el.owner)] if el.owner else [],
            "appliedStereotype": lambda el: [Value(s) for s in ix.stereotype_names(el.id)],
            "metaclass": lambda el: [Value(el.kind)],
            "qualifiedName": lambda el: [Value(ix.qualified_name(el.id))],
            "multiplicity": lambda el: [Value(m)] if (m := sem.multiplicity(ix, el)) else [],
            "specification": lambda el: [Value(t) for c in sem.children(ix, el, "specification")
                                         if (t := sem.value_text(ix, c))],
        }
        if prop in simple:
            return simple[prop]
        if prop in ("Id", "Text") and any(sem.is_requirement(ix, r) for r in rows):
            return lambda el: [Value(to_text(sem.requirement_fields(ix, el).get(prop, "")))]
        rel = RELATION_PROPERTIES.get(prop.replace(" ", "").lower())
        if rel is not None:
            kind, out = rel
            return lambda el: [Value(sem.label(ix, o), o) for o in self.related.get((el.id, kind, out), [])]
        # A tag (of any element in the model: a row may leave it unset), or a model attribute or a
        # reference of that name that some row has.
        if any(prop in a.tags for a in ix.stereotypes.values()):
            return lambda el: _once([v for a in ix.applications(el.id) for v in _values(ix, a.tags.get(prop, []))])
        if any(prop in r.attrs for r in rows):
            return lambda el: [Value(shown_value(to_text(el.attrs[prop])))] if prop in el.attrs else []
        if any(role == prop for r in rows for role, _ in r.refs):
            return lambda el: _values(ix, [t for role, t in el.refs if role == prop])
        return None  # a property a profile derives: Cameo's to compute

    def _slot(self, el: Element, feature: str) -> Cell:
        ix = self.ix
        out = []
        for slot in sem.children(ix, el):
            if slot.kind == "Slot" and feature in sem.refs(slot, "definingFeature"):
                for v in sem.children(ix, slot):
                    inst = sem.refs(v, "instance")
                    text = sem.value_text(ix, v)
                    if text is not None:
                        out.append(Value(text, inst[0] if inst and inst[0] in ix.elements else None))
        return out


def text_of(cell: Cell) -> str:
    return "; ".join(v.text for v in cell if v.text)


def build(ix: ModelIndex, columns: Columns, dia_id: str) -> Table | None:
    """The table a diagram shows, computed; None when it lists no columns or no rows."""
    tags = configuration(ix, dia_id)
    hidden = set(tags.get("hideColumns", []))
    ids = [c for c in tags.get("columnIds", []) if c not in hidden and c != "_EMPTY_"]
    seen: set[str] = set()
    rows = [x for k in ("rowElements", "additionalElements") for x in tags.get(k, [])
            if x in ix.elements and not (x in seen or seen.add(x))]
    if not ids or not rows:
        return None
    els = [ix.elements[r] for r in rows]
    cols = [columns.column(c, els) for c in ids]
    sort = ""
    spec = (tags.get("sort") or [""])[0]
    if spec:
        cid, _, way = spec.partition("^")
        key = columns.column(cid, els)
        if key.read is not None:
            down = way.lower().startswith("desc")
            pairs = sorted(zip(rows, els, strict=True), key=lambda p: natural_key(text_of(key.read(p[1]))), reverse=down)
            rows, els = [p[0] for p in pairs], [p[1] for p in pairs]
            sort = f"{key.header}, {'descending' if down else 'ascending'}"
    cells = [[[Value(str(i))] if c.id == NUMBER else (c.read(el) if c.read else []) for c in cols]
             for i, el in enumerate(els, 1)]
    return Table(cols, rows, cells, sort, [sem.label(ix, t) for t in tags.get("rowElementType", [])],
                 [s for s in tags.get("scope", []) if s in ix.elements])

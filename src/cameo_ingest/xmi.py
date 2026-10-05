"""Streaming, schema-agnostic XMI reader.

The reader does not hard-code UML metamodel knowledge. It relies only on XMI
conventions that are stable across MagicDraw / Cameo versions:

* nodes with `xmi:id` are model elements; their XML tag is their role under the owner;
* child nodes with `xmi:idref` or `href` are references;
* other child nodes (e.g. `<body>`) carry scalar values;
* top-level nodes outside the UML namespace that carry `base_*` attributes are
  stereotype applications, whose other attributes / children are tagged values;
* `xmi:Extension` blocks are skipped, except for MagicDraw diagrams (`uml:Diagram`).

Attributes whose value is a space-separated list of known ids become references in a
second pass, so metamodel changes between versions do not break reference detection.
"""

from __future__ import annotations

import logging
import re
from typing import IO

from lxml import etree

from .model import Diagram, Element, ModelIndex, StereotypeApplication
from .richtext import is_html, to_text

log = logging.getLogger(__name__)

SCALAR_ATTRS_NEVER_REFS = {"name", "body", "value", "visibility", "aggregation", "Text", "Id"}

# Only the bare versioned namespaces, e.g. http://www.omg.org/spec/UML/20131001 or
# http://schema.omg.org/spec/XMI/2.1. Cameo declares profiles below the UML namespace
# (.../UML/20131001/StandardProfile, .../MagicDrawProfile); those must keep their own prefix.
_OMG_NS = re.compile(r"https?://(?:www|schema)\.omg\.org/spec/(UML|XMI)/[\d.]+/?")


def _prefix_for(uri: str, uri2prefix: dict[str, str]) -> str:
    # Normalize the versioned OMG namespaces so downstream code can rely on "uml"/"xmi".
    m = _OMG_NS.fullmatch(uri)
    if m:
        return m.group(1).lower()
    return uri2prefix.get(uri, uri)


class _Parser:
    def __init__(self, index: ModelIndex, entry: str):
        self.ix = index
        self.entry = entry
        self.uri2prefix: dict[str, str] = {}
        self.xmi_uri = "http://www.omg.org/spec/XMI/20131001"
        # Stack of (frame kind, payload). Kinds: root, element, value, ignore, ext,
        # diagram, stereo, doc.
        self.stack: list[tuple[str, object]] = []

    # -- helpers ---------------------------------------------------------------
    def qname(self, tag: str) -> tuple[str, str]:
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            return _prefix_for(uri, self.uri2prefix), local
        return "", tag

    def xattr(self, node, name: str) -> str | None:
        v = node.get(f"{{{self.xmi_uri}}}{name}")
        if v is None:
            # Tolerate documents with a different XMI namespace version.
            for k, val in node.attrib.items():
                if k.endswith("}" + name) and "XMI" in k:
                    return val
        return v

    def plain_attrs(self, node) -> dict[str, str]:
        out = {}
        for k, v in node.attrib.items():
            if k.startswith("{"):
                uri, local = k[1:].split("}", 1)
                if _prefix_for(uri, self.uri2prefix) == "xmi":
                    continue
                k = local
            out[k] = v
        return out

    # -- events ----------------------------------------------------------------
    def start(self, node) -> None:
        prefix, local = self.qname(node.tag)
        parent_kind, parent = self.stack[-1] if self.stack else ("none", None)
        xid = self.xattr(node, "id")
        line = node.sourceline

        if parent_kind == "none":
            if prefix == "xmi" and local == "XMI":
                self.stack.append(("root", None))
            else:  # a bare uml:Model / uml:Package document
                self.stack.append(("root", None))
                self.start(node)  # re-dispatch as a root child
                self.stack.pop(-2)
            return

        if parent_kind == "root":
            if prefix == "xmi" and local == "Documentation":
                self.stack.append(("doc", None))
                return
            if prefix == "xmi" and local == "Extension":
                self.stack.append(("ext", None))
                return
            base_attrs = [k for k in node.attrib if self.qname(k)[1].startswith("base_")]
            if prefix not in ("uml", "xmi") and base_attrs and xid:
                base = node.get(base_attrs[0])
                tags: dict[str, list[str]] = {}
                for k, v in self.plain_attrs(node).items():
                    if not k.startswith("base_"):
                        tags.setdefault(k, []).append(v)
                app = StereotypeApplication(
                    id=xid,
                    stereotype=f"{prefix}:{local}",
                    profile_uri=node.tag[1:].split("}", 1)[0] if node.tag.startswith("{") else "",
                    base=base or "",
                    tags=tags,
                    entry=self.entry,
                    line=line,
                )
                self.ix.stereotypes[xid] = app
                self.stack.append(("stereo", app))
                return
            if xid:
                el = self._element(node, xid, prefix, local, owner=None)
                self.ix.roots.append(xid)
                self.stack.append(("element", el))
                return
            self.stack.append(("ignore", None))
            return

        if parent_kind == "doc":
            self.stack.append(("docvalue", local))
            return

        if parent_kind == "element":
            owner: Element = parent  # type: ignore[assignment]
            if prefix == "xmi" and local == "Extension":
                self.stack.append(("ext", owner))
                return
            if xid:
                el = self._element(node, xid, prefix, local, owner=owner.id)
                owner.children.append(xid)
                self.stack.append(("element", el))
                return
            idref = self.xattr(node, "idref") or node.get("href")
            if idref:
                owner.refs.append((local, idref))
                if node.get("href") and not idref.startswith("#"):
                    self.ix.external_refs.add(idref)
                self.stack.append(("ignore", None))
                return
            self.stack.append(("value", (owner, local)))
            return

        if parent_kind == "stereo":
            app: StereotypeApplication = parent  # type: ignore[assignment]
            ref = self.xattr(node, "idref") or node.get("href")
            if ref:
                app.tags.setdefault(local, []).append(ref)
                if node.get("href") and not ref.startswith("#"):
                    self.ix.external_refs.add(ref)
                self.stack.append(("ignore", None))
            else:
                self.stack.append(("stereovalue", (app, local)))
            return

        if parent_kind == "ext":
            if self.xattr(node, "type") == "uml:Diagram" and xid:
                owner_el = parent if isinstance(parent, Element) else None
                owner_id = node.get("ownerOfDiagram") or (owner_el.id if owner_el else None)
                el = self._element(node, xid, "uml", local, owner=owner_id)
                if owner_el is not None:
                    owner_el.children.append(xid)
                dia = Diagram(
                    id=xid, name=node.get("name") or "", owner=owner_id, diagram_type=None,
                    uml_type=None, entry=self.entry, line=line,
                )
                self.ix.diagrams[xid] = dia
                self.stack.append(("diagram", (el, dia)))
                return
            self.stack.append(("ext", parent))
            return

        if parent_kind in ("diagram", "diagram_inner"):
            el, dia = parent  # type: ignore[misc]
            if node.get("umlType") or (local == "DiagramRepresentationObject"):
                dia.diagram_type = dia.diagram_type or node.get("type")
                dia.uml_type = dia.uml_type or node.get("umlType")
            sid = node.get("streamContentID")
            if sid:
                dia.streams.append(sid)
            ref = self.xattr(node, "idref")
            if not ref and local == "usedObjects" and (node.get("href") or "").startswith("#"):
                ref = node.get("href")[1:]  # how Cameo writes them: href='#id' (BASE-013)
            if ref:
                dia.shown.append(ref)
                if local == "usedObjects":
                    dia.used.append(ref)
            if local == "ownedComment" and xid:  # diagram documentation
                self.stack.append(("element", self._element(node, xid, prefix, local, owner=el.id)))
                el.children.append(xid)
                return
            self.stack.append(("diagram_inner", parent))
            return

        self.stack.append(("ignore", None))

    def end(self, node) -> None:
        kind, payload = self.stack.pop()
        text = (node.text or "").strip()
        if kind == "value" and text:
            owner, role = payload  # type: ignore[misc]
            prev = owner.attrs.get(role)
            owner.attrs[role] = f"{prev}\n{text}" if prev else text
        elif kind == "stereovalue" and text:
            app, role = payload  # type: ignore[misc]
            app.tags.setdefault(role, []).append(text)
        elif kind == "docvalue" and text:
            self.ix.exporter[payload] = text  # type: ignore[index]

    def _element(self, node, xid: str, prefix: str, local: str, owner: str | None) -> Element:
        xtype = self.xattr(node, "type") or (f"{prefix}:{local}" if prefix else local)
        attrs = self.plain_attrs(node)
        el = Element(
            id=xid,
            type=xtype,
            role=local,
            name=attrs.pop("name", None),
            owner=owner,
            entry=self.entry,
            line=node.sourceline,
            attrs=attrs,
        )
        if xid in self.ix.elements:
            log.debug("duplicate xmi:id %s in %s", xid, self.entry)
        self.ix.elements[xid] = el
        return el


def parse_into(index: ModelIndex, stream: IO[bytes], entry: str) -> None:
    p = _Parser(index, entry)
    events = etree.iterparse(
        stream,
        events=("start-ns", "start", "end"),
        huge_tree=True,
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_comments=True,
        remove_pis=True,
    )
    for event, node in events:
        if event == "start-ns":
            prefix, uri = node
            p.uri2prefix.setdefault(uri, prefix or "")
            norm = _prefix_for(uri, p.uri2prefix)
            if norm == "xmi":
                p.xmi_uri = uri
            index.namespaces.setdefault(norm, uri)
        elif event == "start":
            p.start(node)
        else:
            p.end(node)
            # Free memory as we go; we keep our own compact index.
            node.clear(keep_tail=False)
            parent = node.getparent()
            if parent is not None:
                while node.getprevious() is not None:
                    del parent[0]


def finalize(index: ModelIndex) -> None:
    """Second pass: link stereotypes, turn id-valued attributes into references."""
    for app in index.stereotypes.values():
        el = index.elements.get(app.base)
        if el is not None:
            el.stereotypes.append(app.id)
    ids = index.elements

    def own(ref: str) -> str:
        """An href to one of the project's own elements is a reference to it: Cameo writes the
        Model's packages kept in its shared part as `local:/PROJECT-<its id>?resource=…#id`."""
        frag = ref.rsplit("#", 1)[-1]
        return frag if ref in index.external_refs and frag in ids else ref

    for el in ids.values():
        el.refs = [(k, own(r)) for k, r in el.refs]
    for el in ids.values():
        for k in list(el.attrs):
            if k in SCALAR_ATTRS_NEVER_REFS:
                continue
            toks = el.attrs[k].split()
            if toks and all(t in ids for t in toks):
                del el.attrs[k]
                el.refs.extend((k, t) for t in toks)
    # Rich text (documentation, requirement text, string tags) is stored as HTML.
    for el in ids.values():
        for k, v in el.attrs.items():
            if "<" in v and is_html(v):
                el.attrs[k] = to_text(v)
    for app in index.stereotypes.values():
        for k, vals in app.tags.items():
            out: list[str] = []
            for v in vals:
                toks = v.split()
                if len(toks) > 1 and all(t in ids for t in toks):
                    out += toks  # an id list stored as one attribute, e.g. a table's scope
                else:
                    out.append(to_text(v) if "<" in v and is_html(v) else own(v))
            app.tags[k] = out
    index.external_refs = {r for r in index.external_refs if own(r) == r}
    for dia in index.diagrams.values():
        dia.shown = list(dict.fromkeys(s for s in dia.shown if s in ids))
        dia.used = list(dict.fromkeys(s for s in dia.used if s in ids))

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

Names that XML namespaces can't split (`a:b:c`, `a:`) are read as written, and reported
(`read_events`, TR-001); any other fault in the XML still fails the entry.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import IO, Any

from lxml import etree

from .model import Diagram, Element, ModelIndex, StereotypeApplication
from .richtext import is_html, to_text

log = logging.getLogger(__name__)

SCALAR_ATTRS_NEVER_REFS = {"name", "body", "value", "visibility", "aggregation", "Text", "Id"}

# Only the bare versioned namespaces, e.g. http://www.omg.org/spec/UML/20131001 or
# http://schema.omg.org/spec/XMI/2.1. Cameo declares profiles below the UML namespace
# (.../UML/20131001/StandardProfile, .../MagicDrawProfile); those must keep their own prefix.
_OMG_NS = re.compile(r"https?://(?:www|schema)\.omg\.org/spec/(UML|XMI)/[\d.]+/?")


class ModelReadError(ValueError):
    """An entry's XML is damaged beyond names: truncated, a bad character, and so on."""


def read_events(stream: IO[bytes], events: tuple[str, ...], entry: str,
                recovered: dict[str, list[str]] | None = None) -> Iterator[tuple[str, Any]]:
    """`etree.iterparse`'s events, recovering from names that XML namespaces can't split, such as
    `a:b:c` or `a:` (TR-001): libxml2 refuses them, and in recovery keeps them as literal names,
    with every element, id and attribute. Those faults go in `recovered[entry]`; any other fault
    raises `ModelReadError` once the entry is read, as a damaged file did before."""
    it = etree.iterparse(stream, events=events, recover=True, huge_tree=True, resolve_entities=False,
                         no_network=True, load_dtd=False, remove_comments=True, remove_pis=True)
    yield from it
    names, other = [], []
    for e in it.error_log:
        if e.level_name in ("ERROR", "FATAL"):
            (names if e.domain_name == "NAMESPACE" else other).append(f"line {e.line}: {e.message}")
    if other:
        raise ModelReadError(f"damaged XML in {entry}, {other[0]}" + (f" (and {len(other) - 1} more)" if len(other) > 1 else ""))
    if names and recovered is not None:
        recovered[entry] = names


def _prefix_for(uri: str, uri2prefix: dict[str, str]) -> str:
    # Normalize the versioned OMG namespaces so downstream code can rely on "uml"/"xmi".
    m = _OMG_NS.fullmatch(uri)
    if m:
        return m.group(1).lower()
    return uri2prefix.get(uri, uri)


class _Frame:
    """An open XML element of the model, as the parser reads it (CQ-019): what its children are
    (`child`), and what its text says when it ends (`close`). A frame of one kind for each place
    in the document that reads differently."""

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        return _IGNORE

    def close(self, p: _Parser, text: str) -> None:
        pass


class _Ignored(_Frame):
    """Something read no further: its children are ignored too."""


_IGNORE = _Ignored()


class _Root(_Frame):
    """`xmi:XMI`'s children: the documentation, extensions, stereotype applications (an element of
    a profile's namespace with a `base_` attribute) and the model's top elements."""

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        if prefix == "xmi" and local == "Documentation":
            return _Doc()
        if prefix == "xmi" and local == "Extension":
            return _Ext(None)
        base_attrs = [k for k in node.attrib if p.qname(k)[1].startswith("base_")]
        if prefix not in ("uml", "xmi") and base_attrs and xid:
            tags: dict[str, list[str]] = {}
            for k, v in p.plain_attrs(node).items():
                if not k.startswith("base_"):
                    tags.setdefault(k, []).append(v)
            app = StereotypeApplication(
                id=xid,
                stereotype=f"{prefix}:{local}",
                profile_uri=node.tag[1:].split("}", 1)[0] if node.tag.startswith("{") else p.literal_ns.get(prefix, ""),
                base=node.get(base_attrs[0]) or "",
                tags=tags,
                entry=p.entry,
                line=node.sourceline,
            )
            p.ix.stereotypes[xid] = app
            return _Stereo(app)
        if xid:
            el = p._element(node, xid, prefix, local, owner=None)
            p.ix.roots.append(xid)
            return _Owned(el)
        return _IGNORE


class _Doc(_Frame):
    """`xmi:Documentation`: the exporter's name and version."""

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        return _DocValue(local)


class _DocValue(_Frame):
    def __init__(self, key: str):
        self.key = key

    def close(self, p: _Parser, text: str) -> None:
        if text:
            p.ix.exporter[self.key] = text


class _Owned(_Frame):
    """An element's children: owned elements, references (`xmi:idref`, `href`), extensions, and
    property values written as elements."""

    def __init__(self, el: Element):
        self.el = el

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        owner = self.el
        if prefix == "xmi" and local == "Extension":
            return _Ext(owner)
        if xid:
            el = p._element(node, xid, prefix, local, owner=owner.id)
            owner.children.append(xid)
            return _Owned(el)
        idref = p.xattr(node, "idref") or node.get("href")
        if idref:
            owner.refs.append((local, idref))
            if node.get("href") and not idref.startswith("#"):
                p.ix.external_refs.add(idref)
            return _IGNORE
        return _Value(owner, local)


class _Value(_Frame):
    """A property's value written as an element's text; a repeated one joins by lines."""

    def __init__(self, owner: Element, role: str):
        self.owner, self.role = owner, role

    def close(self, p: _Parser, text: str) -> None:
        if text:
            prev = self.owner.attrs.get(self.role)
            self.owner.attrs[self.role] = f"{prev}\n{text}" if prev else text


class _Stereo(_Frame):
    """A stereotype application's tagged values written as elements: references or text."""

    def __init__(self, app: StereotypeApplication):
        self.app = app

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        ref = p.xattr(node, "idref") or node.get("href")
        if ref:
            self.app.tags.setdefault(local, []).append(ref)
            if node.get("href") and not ref.startswith("#"):
                p.ix.external_refs.add(ref)
            return _IGNORE
        return _StereoValue(self.app, local)


class _StereoValue(_Frame):
    def __init__(self, app: StereotypeApplication, role: str):
        self.app, self.role = app, role

    def close(self, p: _Parser, text: str) -> None:
        if text:
            self.app.tags.setdefault(self.role, []).append(text)


class _Ext(_Frame):
    """`xmi:Extension` (of an element, or at the root): diagrams, at any depth; the rest ignored."""

    def __init__(self, owner: Element | None):
        self.owner = owner

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        if p.xattr(node, "type") == "uml:Diagram" and xid:
            owner_id = node.get("ownerOfDiagram") or (self.owner.id if self.owner else None)
            el = p._element(node, xid, "uml", local, owner=owner_id)
            if self.owner is not None:
                self.owner.children.append(xid)
            dia = Diagram(id=xid, name=node.get("name") or "", owner=owner_id, diagram_type=None,
                          uml_type=None, entry=p.entry, line=node.sourceline)
            p.ix.diagrams[xid] = dia
            return _InDiagram(el, dia)
        return _Ext(self.owner)


class _InDiagram(_Frame):
    """A diagram's contents, at any depth: its type, the streams of its layout, what it shows
    (`usedObjects`), and its documentation (an owned comment)."""

    def __init__(self, el: Element, dia: Diagram):
        self.el, self.dia = el, dia

    def child(self, p: _Parser, node, prefix: str, local: str, xid: str | None) -> _Frame:
        dia = self.dia
        if node.get("umlType") or (local == "DiagramRepresentationObject"):
            dia.diagram_type = dia.diagram_type or node.get("type")
            dia.uml_type = dia.uml_type or node.get("umlType")
        sid = node.get("streamContentID")
        if sid:
            dia.streams.append(sid)
        ref = p.xattr(node, "idref")
        if not ref and local == "usedObjects" and (node.get("href") or "").startswith("#"):
            ref = node.get("href")[1:]  # how Cameo writes them: href='#id' (BASE-013)
        if ref:
            dia.shown.append(ref)
            if local == "usedObjects":
                dia.used.append(ref)
        if local == "ownedComment" and xid:  # diagram documentation
            frame = _Owned(p._element(node, xid, prefix, local, owner=self.el.id))
            self.el.children.append(xid)
            return frame
        return self


class _Parser:
    def __init__(self, index: ModelIndex, entry: str):
        self.ix = index
        self.entry = entry
        self.uri2prefix: dict[str, str] = {}
        # Namespaces declared with a prefix XML can't take, such as Cameo's
        # `xmlns:MD_Customization_for_SysML::additional_stereotypes` (TR-001): read as written.
        self.literal_ns: dict[str, str] = {}
        self.xmi_uri = "http://www.omg.org/spec/XMI/20131001"
        self.stack: list[_Frame] = []  # the open elements' frames

    # -- helpers ---------------------------------------------------------------
    def qname(self, tag: str) -> tuple[str, str]:
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            return _prefix_for(uri, self.uri2prefix), local
        if ":" in tag:  # a name namespaces couldn't split, read as written (TR-001): a prefix may hold
            prefix, local = tag.rsplit(":", 1)  # "::", a local name never a colon
            return prefix, local
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
        if not self.stack:  # the document's root
            for k, v in node.attrib.items():
                if k.startswith("xmlns:"):  # a declaration XML refused, kept as an attribute (TR-001)
                    self.literal_ns[k[6:]] = v
                    self.ix.namespaces.setdefault(k[6:], v)
            self.stack.append(_Root())
            if not (prefix == "xmi" and local == "XMI"):  # a bare uml:Model / uml:Package document
                self.stack.append(self.stack[-1].child(self, node, prefix, local, self.xattr(node, "id")))
                self.stack.pop(-2)
            return
        self.stack.append(self.stack[-1].child(self, node, prefix, local, self.xattr(node, "id")))

    def end(self, node) -> None:
        self.stack.pop().close(self, (node.text or "").strip())

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
    for event, node in read_events(stream, ("start-ns", "start", "end"), entry, index.recovered):
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

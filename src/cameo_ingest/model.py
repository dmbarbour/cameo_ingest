"""In-memory model index built from one project's XMI entries."""

from __future__ import annotations

from dataclasses import dataclass, field

from .external import external_label


@dataclass
class Element:
    id: str
    type: str  # e.g. "uml:Class"; for untyped nodes the qualified tag
    role: str  # the XML tag under its owner, e.g. "packagedElement", "ownedAttribute"
    name: str | None
    owner: str | None
    entry: str
    line: int | None
    attrs: dict[str, str] = field(default_factory=dict)  # scalar properties
    refs: list[tuple[str, str]] = field(default_factory=list)  # (role, target id or href)
    children: list[str] = field(default_factory=list)
    stereotypes: list[str] = field(default_factory=list)  # ids of StereotypeApplications

    @property
    def kind(self) -> str:
        return self.type.split(":", 1)[-1]


@dataclass
class StereotypeApplication:
    id: str
    stereotype: str  # "prefix:Name", e.g. "sysml:Requirement"
    profile_uri: str
    base: str  # id of the extended element
    tags: dict[str, list[str]]  # tagged values; element references are left as ids
    entry: str
    line: int | None

    @property
    def name(self) -> str:
        return self.stereotype.split(":", 1)[-1]


@dataclass
class Diagram:
    id: str
    name: str
    owner: str | None
    diagram_type: str | None  # e.g. "SysML Block Definition Diagram"
    uml_type: str | None  # e.g. "Class Diagram"
    streams: list[str] = field(default_factory=list)  # archive entries holding layout
    shown: list[str] = field(default_factory=list)  # ids of the elements drawn; without a layout, `usedObjects`
    used: list[str] = field(default_factory=list)  # `usedObjects`, as Cameo saved them (plan IS)
    entry: str = ""
    line: int | None = None


@dataclass
class ModelIndex:
    elements: dict[str, Element] = field(default_factory=dict)
    stereotypes: dict[str, StereotypeApplication] = field(default_factory=dict)
    diagrams: dict[str, Diagram] = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)
    namespaces: dict[str, str] = field(default_factory=dict)  # prefix -> uri
    exporter: dict[str, str] = field(default_factory=dict)
    external_refs: set[str] = field(default_factory=set)  # href targets outside this project
    recovered: dict[str, list[str]] = field(default_factory=dict)  # entry: names read as written (TR-001)
    external: dict[str, str] = field(default_factory=dict)  # their names, by id (external.proxy_names)
    _qn_cache: dict[str, str] = field(default_factory=dict, repr=False)

    def get(self, id_: str | None) -> Element | None:
        return self.elements.get(id_) if id_ else None

    def qualified_name(self, id_: str) -> str:
        # Cached: the index is not modified once parsing has finished.
        qn = self._qn_cache.get(id_)
        if qn is None:
            qn = self._qn_cache[id_] = self._qualified_name(id_)
        return qn

    def _qualified_name(self, id_: str) -> str:
        parts = []
        seen = set()
        cur = self.elements.get(id_)
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            if cur.name:
                parts.append(cur.name)
            cur = self.elements.get(cur.owner) if cur.owner else None
        return "::".join(reversed(parts))

    def stereotype_names(self, id_: str) -> list[str]:
        el = self.elements.get(id_)
        if not el:
            return []
        return [self.stereotypes[s].name for s in el.stereotypes if s in self.stereotypes]

    def applications(self, id_: str, name: str | None = None) -> list[StereotypeApplication]:
        el = self.elements.get(id_)
        if not el:
            return []
        apps = [self.stereotypes[s] for s in el.stereotypes if s in self.stereotypes]
        return [a for a in apps if name is None or a.name == name]

    def refers(self, value: str) -> bool:
        """Whether a value (a tagged value, say) is a reference to an element, here or outside."""
        return value in self.elements or value in self.external_refs

    def label(self, id_: str) -> str:
        """A generic label: the name, or "(unnamed Kind)", or a reference's last part. How an
        element reads on pages, in chunks and in diagrams is `semantics.label` (AR-010)."""
        el = self.elements.get(id_)
        if el is None:
            return external_label(self.external, id_)
        return el.name or f"(unnamed {el.kind})"

"""UML / SysML interpretation on top of the generic XMI index.

Everything here is best-effort: unknown element kinds still get emitted generically,
these helpers just make the common cases read well.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Element, ModelIndex

# Roles whose targets deserve their own section / chunk. Everything else is described
# inside its owner's section (attributes, ports, operations, literals, ...).
SECTION_ROLES = {
    "packagedElement", "ownedBehavior", "nestedClassifier", "ownedUseCase",
    "ownedDiagram", "nestedPackage", "ownedStereotype", "classifierBehavior",
}
PACKAGE_KINDS = {"Model", "Package", "Profile"}

# (source role, target role) pairs used to read directed relationships generically.
END_ROLES = [
    ("client", "supplier"),
    ("source", "target"),
    ("informationSource", "informationTarget"),
    ("includingCase", "addition"),
    ("extension", "extendedCase"),
    ("specific", "general"),
    ("sendEvent", "receiveEvent"),
]
RELATIONSHIP_KINDS = {
    "Dependency", "Abstraction", "Realization", "Usage", "Generalization",
    "InterfaceRealization", "Association", "AssociationClass", "Connector",
    "ControlFlow", "ObjectFlow", "Transition", "Include", "Extend",
    "InformationFlow", "Message", "PackageImport", "ElementImport",
    "Substitution", "ComponentRealization", "TemplateBinding", "ProfileApplication",
}
REQUIREMENT_HINTS = {"Id", "Text"}


@dataclass
class Relationship:
    id: str
    kind: str  # stereotype name if present (e.g. "satisfy"), else metaclass
    metaclass: str
    source: str
    target: str
    name: str | None


def is_section(ix: ModelIndex, el: Element) -> bool:
    if el.kind in RELATIONSHIP_KINDS:
        return False
    if el.kind in PACKAGE_KINDS or el.kind == "Diagram":
        return True
    if el.role in SECTION_ROLES:
        return True
    return is_requirement(ix, el)


def is_requirement(ix: ModelIndex, el: Element) -> bool:
    """SysML «requirement» and its specializations (incl. custom profiles such as
    «TMT_Requirement» or «functionalRequirement»), recognized by name or by Id/Text tags."""
    if el.kind not in ("Class", "Requirement"):
        return False
    for app in ix.applications(el.id):
        if app.name.lower().endswith("requirement") or REQUIREMENT_HINTS <= set(app.tags):
            return True
    return False


def requirement_fields(ix: ModelIndex, el: Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for app in ix.applications(el.id):
        for k in ("Id", "Text", "id", "text"):
            if k in app.tags and k.capitalize() not in out:
                out[k.capitalize()] = "\n".join(app.tags[k])
    return out


def refs(el: Element, role: str) -> list[str]:
    return [t for r, t in el.refs if r == role]


def children(ix: ModelIndex, el: Element, role: str | None = None) -> list[Element]:
    out = []
    for cid in el.children:
        c = ix.elements.get(cid)
        if c is not None and (role is None or c.role == role):
            out.append(c)
    return out


def documentation(ix: ModelIndex, el: Element) -> str:
    """MagicDraw stores element documentation as an owned Comment annotating the owner."""
    parts = []
    for c in children(ix, el, "ownedComment"):
        body = c.attrs.get("body", "").strip()
        annotated = refs(c, "annotatedElement")
        if body and (not annotated or el.id in annotated):
            parts.append(body)
    return "\n\n".join(parts)


def value_text(ix: ModelIndex, v: Element | None) -> str | None:
    """Render a ValueSpecification (literal, opaque expression, instance value...)."""
    if v is None:
        return None
    k = v.kind
    if k == "LiteralNull":
        return "null"
    if k in ("LiteralInteger", "LiteralReal", "LiteralUnlimitedNatural"):
        return v.attrs.get("value", "0")
    if k == "LiteralBoolean":
        return v.attrs.get("value", "false")
    if k == "LiteralString":
        return v.attrs.get("value", "")
    if k in ("OpaqueExpression", "OpaqueBehavior"):
        return v.attrs.get("body")
    if k == "InstanceValue":
        inst = refs(v, "instance")
        return ix.label(inst[0]) if inst else None
    if k == "ElementValue":
        e = refs(v, "element")
        return ix.label(e[0]) if e else None
    if k == "Expression":
        ops = [value_text(ix, o) for o in children(ix, v, "operand")]
        sym = v.attrs.get("symbol", "")
        return f"{sym}({', '.join(o or '' for o in ops)})" if sym else " ".join(o or "" for o in ops)
    return v.attrs.get("value") or v.attrs.get("body") or v.name


def multiplicity(ix: ModelIndex, el: Element) -> str | None:
    lo_el = next(iter(children(ix, el, "lowerValue")), None)
    hi_el = next(iter(children(ix, el, "upperValue")), None)
    if lo_el is None and hi_el is None:
        return None
    lo = value_text(ix, lo_el) if lo_el is not None else "1"
    hi = value_text(ix, hi_el) if hi_el is not None else "1"
    if hi == "-1":
        hi = "*"
    return lo if lo == hi else f"{lo}..{hi}"


def type_label(ix: ModelIndex, el: Element) -> str | None:
    t = refs(el, "type")
    return ix.label(t[0]) if t else None


def relationships(ix: ModelIndex) -> list[Relationship]:
    out: list[Relationship] = []
    for el in ix.elements.values():
        if el.kind not in RELATIONSHIP_KINDS:
            continue
        st = ix.stereotype_names(el.id)
        kind = st[0] if st else el.kind
        pairs: list[tuple[str, str]] = []
        if el.kind == "Generalization":
            pairs = [(el.owner or "", t) for t in refs(el, "general")]
        elif el.kind == "Include":
            pairs = [(el.owner or "", t) for t in refs(el, "addition")]
        elif el.kind == "Extend":
            pairs = [(el.owner or "", t) for t in refs(el, "extendedCase")]
        elif el.kind in ("InterfaceRealization", "PackageImport", "ElementImport", "ProfileApplication"):
            tgt_role = {"InterfaceRealization": "contract", "PackageImport": "importedPackage",
                        "ElementImport": "importedElement", "ProfileApplication": "appliedProfile"}[el.kind]
            pairs = [(el.owner or "", t) for t in refs(el, tgt_role) or refs(el, "supplier")]
        elif el.kind in ("Association", "AssociationClass"):
            ends = refs(el, "memberEnd")
            types = []
            for e in ends:
                end = ix.elements.get(e)
                t = refs(end, "type") if end else []
                types.append(t[0] if t else e)
            if len(types) == 2:
                pairs = [(types[0], types[1])]
        elif el.kind == "Connector":
            ends = children(ix, el, "end")
            roles = [(refs(e, "role") or [""])[0] for e in ends]
            if len(roles) == 2:
                pairs = [(roles[0], roles[1])]
        else:
            for s_role, t_role in END_ROLES:
                ss, ts = refs(el, s_role), refs(el, t_role)
                if ss and ts:
                    pairs = [(s, t) for s in ss for t in ts]
                    break
        for s, t in pairs:
            if s and t:
                out.append(Relationship(el.id, kind, el.kind, s, t, el.name))
    return out

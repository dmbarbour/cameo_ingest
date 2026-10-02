"""A builder for fictional Cameo projects, in the XMI and layout format Cameo writes, with
questions whose answers are known by construction (plan RE, RE-10).

A project is described in Python, element by element, under short keys. Every element id is
the key under the project's prefix (`_rwt_filter`), so that a chunk's `element_id` says which
project it is from, and the answer key can name elements before the project is built:

    p = Project("Riverbend Water Treatment Works", "rwt")
    pkg = p.package("proc", "Treatment Process")
    p.block("filter", "Dual Media Filter", pkg, doc="...", values=[("headLossLimit", "m", 2.4)])
    p.ask("q01", "parameter", "medium", "At what head loss ...?", "When does a filter ...?",
          answers=["filter"], evidence="2.4")

`Project.mdzip()` returns the archive (the same bytes every time), and `Project.questions()` the
questions, each asked literally (with the model's names) and as a paraphrase. A question's
`evidence` is a phrase, or alternatives, that the answering elements' chunks must hold; the
tests check it, so that the answer key can't drift from the model.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

NAMESPACES = {
    "xmi": "http://www.omg.org/spec/XMI/20131001",
    "uml": "http://www.omg.org/spec/UML/20131001",
    "sysml": "http://www.omg.org/spec/SysML/20181001/SysML",
    "StandardProfile": "http://www.omg.org/spec/UML/20131001/StandardProfile",
}
DIAGRAM_TYPES = {  # diagram type -> UML diagram type, as Cameo writes them
    "SysML Block Definition Diagram": "Class Diagram",
    "SysML Internal Block Diagram": "Composite Structure Diagram",
    "Requirement Diagram": "Class Diagram",
    "SysML Activity Diagram": "Activity Diagram",
    "SysML State Machine Diagram": "State Machine Diagram",
    "SysML Package Diagram": "Package Diagram",
    "SysML Parametric Diagram": "Composite Structure Diagram",
}
RELATION_STEREOTYPES = {  # relation kind -> (profile, stereotype)
    "satisfy": ("sysml", "Satisfy"), "deriveReqt": ("sysml", "DeriveReqt"), "verify": ("sysml", "Verify"),
    "allocate": ("sysml", "Allocate"), "refine": ("StandardProfile", "Refine"),
    "trace": ("StandardProfile", "Trace"), "copy": ("sysml", "Copy"),
}
_LITERALS = {bool: "LiteralBoolean", int: "LiteralInteger", float: "LiteralReal", str: "LiteralString"}


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or "x"


def _literal(id_: str, value: object, tag: str = "defaultValue") -> str:
    kind = _LITERALS[type(value)]
    text = str(value).lower() if isinstance(value, bool) else str(value)
    return f"<{tag} xmi:type='uml:{kind}' xmi:id='{id_}' value={quoteattr(text)}/>"


@dataclass
class _Node:
    """An XML element whose children are added as the project is described."""

    head: str
    tail: str
    children: list[_Node | str] = field(default_factory=list)

    def render(self) -> str:
        return self.head + "".join(c if isinstance(c, str) else c.render() for c in self.children) + self.tail


@dataclass
class _Shape:
    view: str
    cls: str
    element: str
    rect: tuple[int, int, int, int]
    nested: list[_Shape] = field(default_factory=list)


class Project:
    """A fictional project: packages, elements, relationships, diagrams and questions."""

    def __init__(self, name: str, prefix: str, file_name: str | None = None, folder: str = ""):
        self.name, self.prefix = name, prefix
        self.file_name = file_name or re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") + ".mdzip"
        self.folder = folder  # where the file goes, apart from others of the same name
        self.namespaces = dict(NAMESPACES)
        self.model = _Node(f"<uml:Model xmi:type='uml:Model' xmi:id='{self.id('model')}' name={quoteattr(name)}>",
                           "</uml:Model>")
        self.nodes: dict[str, _Node] = {"model": self.model}  # key -> the node that owns children
        self.names: dict[str, str] = {"model": name}
        self.kinds: dict[str, str] = {"model": "Model"}  # key -> metaclass (for diagram shapes)
        self.applications: list[str] = []  # stereotype applications, at the root
        self.ends: dict[str, tuple[str, str]] = {}  # relationship key -> (source key, target key)
        self.parts: dict[str, list[tuple[str, str, str]]] = {}  # block -> [(part key, name, type key)]
        self.ports: dict[str, dict[str, str]] = {}  # block -> port name -> port key
        self.values: dict[str, dict[str, str]] = {}  # block -> value name -> property key
        self.connectors: dict[str, list[str]] = {}  # block -> connector keys
        self.flows: dict[str, list[tuple[str, str, str]]] = {}  # behavior -> [(edge key, source, target)]
        self.members: dict[str, list[str]] = {}  # behavior -> node or vertex keys
        self.layouts: dict[str, str] = {}
        self._questions: list[dict] = []

    # -- ids and the tree ------------------------------------------------------------------------
    def id(self, key: str) -> str:
        return f"_{self.prefix}_{key}"

    def _add(self, key: str, parent: str, head: str, tail: str, name: str, kind: str) -> str:
        if key in self.nodes or key in self.names:
            raise ValueError(f"{self.prefix}: key {key!r} used twice")
        node = _Node(head, tail)
        self.nodes[parent].children.append(node)
        self.nodes[key], self.names[key], self.kinds[key] = node, name, kind
        return key

    def _doc(self, key: str, text: str | None) -> None:
        if text:
            self.nodes[key].children.append(
                f"<ownedComment xmi:type='uml:Comment' xmi:id='{self.id(key)}__doc' body={quoteattr(text)}>"
                f"<annotatedElement xmi:idref='{self.id(key)}'/></ownedComment>")

    def apply(self, profile: str, stereotype: str, key: str, base: str = "Class", **tags: object) -> None:
        """Apply a stereotype to element `key`, with tagged values (a list gives several values)."""
        attrs, children = [], []
        for tag, value in tags.items():
            if isinstance(value, (list, tuple)):
                children += [f"<{tag}>{escape(str(v))}</{tag}>" for v in value]
            elif value is not None:
                attrs.append(f" {tag}={quoteattr(str(value))}")
        app_id = f"{self.id(key)}__st_{slug(stereotype)}"
        head = f"<{profile}:{stereotype} xmi:id='{app_id}' base_{base}='{self.id(key)}'{''.join(attrs)}"
        self.applications.append(head + (">" + "".join(children) + f"</{profile}:{stereotype}>" if children else "/>"))

    def profile(self, prefix: str, name: str, stereotypes: dict[str, list[str]], parent: str = "model") -> str:
        """A custom profile (`prefix` is its XML namespace prefix), with stereotypes and their tags."""
        self.namespaces[prefix] = f"http://www.magicdraw.com/schemas/{prefix}.xmi"
        key = self._add(f"prof_{slug(prefix)}", parent,
                        f"<packagedElement xmi:type='uml:Profile' xmi:id='{self.id('prof_' + slug(prefix))}' "
                        f"name={quoteattr(name)}>", "</packagedElement>", name, "Profile")
        for st, tags in stereotypes.items():
            sk = self._add(f"{key}_{slug(st)}", key,
                           f"<packagedElement xmi:type='uml:Stereotype' xmi:id='{self.id(key + '_' + slug(st))}' "
                           f"name={quoteattr(st)}>", "</packagedElement>", st, "Stereotype")
            for tag in tags:
                self.nodes[sk].children.append(
                    f"<ownedAttribute xmi:type='uml:Property' xmi:id='{self.id(sk + '_' + slug(tag))}' "
                    f"name={quoteattr(tag)}/>")
        return key

    # -- structure -------------------------------------------------------------------------------
    def package(self, key: str, name: str, parent: str = "model", doc: str | None = None) -> str:
        self._add(key, parent, f"<packagedElement xmi:type='uml:Package' xmi:id='{self.id(key)}' "
                               f"name={quoteattr(name)}>", "</packagedElement>", name, "Package")
        self._doc(key, doc)
        return key

    def value_type(self, key: str, name: str, pkg: str, unit: str | None = None) -> str:
        self._add(key, pkg, f"<packagedElement xmi:type='uml:DataType' xmi:id='{self.id(key)}' "
                            f"name={quoteattr(name)}>", "</packagedElement>", name, "DataType")
        self.apply("sysml", "ValueType", key, base="DataType", unit=unit)
        return key

    def signal(self, key: str, name: str, pkg: str, doc: str | None = None) -> str:
        self._add(key, pkg, f"<packagedElement xmi:type='uml:Signal' xmi:id='{self.id(key)}' "
                            f"name={quoteattr(name)}>", "</packagedElement>", name, "Signal")
        self._doc(key, doc)
        return key

    def block(self, key: str, name: str, pkg: str, doc: str | None = None, *,
              values: list[tuple] = (), parts: list[tuple] = (), refs: list[tuple] = (),
              ports: list[tuple] = (), general: str | list[str] | None = None,
              stereotype: str | None = "Block", interface: bool = False) -> str:
        """A block. `values`: (name, type, default) or (name, type, default, doc), where a type is a
        value type's key, or None for an untyped value. `parts` and `refs`: (name, block key) or
        (name, block key, multiplicity "lo..hi"). `ports`: (name, interface block key or None)."""
        self._add(key, pkg, f"<packagedElement xmi:type='uml:Class' xmi:id='{self.id(key)}' name={quoteattr(name)}>",
                  "</packagedElement>", name, "Class")
        self._doc(key, doc)
        node = self.nodes[key]
        for g in [general] if isinstance(general, str) else general or []:
            node.children.append(f"<generalization xmi:type='uml:Generalization' xmi:id='{self.id(key)}__gen_{g}' "
                                 f"general='{self.id(g)}'/>")
            self.ends[f"{key}__gen_{g}"] = (key, g)
            self.kinds[f"{key}__gen_{g}"] = "Generalization"
        self.values[key] = {}
        for v in values:
            vname, vtype, default = v[:3]
            pk = f"{key}__v_{slug(vname)}"
            body = _literal(self.id(pk) + "_dv", default) if default is not None else ""
            vdoc = (f"<ownedComment xmi:type='uml:Comment' xmi:id='{self.id(pk)}__doc' body={quoteattr(v[3])}>"
                    f"<annotatedElement xmi:idref='{self.id(pk)}'/></ownedComment>") if len(v) > 3 else ""
            node.children.append(f"<ownedAttribute xmi:type='uml:Property' xmi:id='{self.id(pk)}' name={quoteattr(vname)}"
                                 + (f" type='{self.id(vtype)}'" if vtype else "") + f">{vdoc}{body}</ownedAttribute>")
            self.values[key][vname], self.names[pk], self.kinds[pk] = pk, vname, "Property"
        self.parts[key] = []
        for composite, items in ((True, parts), (False, refs)):
            for item in items:
                pname, ptype = item[:2]
                pk = f"{key}__p_{slug(pname)}"
                mult = ""
                if len(item) > 2:
                    lo, hi = item[2].split("..")
                    mult = (f"<lowerValue xmi:type='uml:LiteralInteger' xmi:id='{self.id(pk)}_lo' value='{lo}'/>"
                            f"<upperValue xmi:type='uml:LiteralUnlimitedNatural' xmi:id='{self.id(pk)}_hi' "
                            f"value='{hi}'/>")
                assoc = f"{key}__as_{slug(pname)}"
                node.children.append(
                    f"<ownedAttribute xmi:type='uml:Property' xmi:id='{self.id(pk)}' name={quoteattr(pname)}"
                    + (" aggregation='composite'" if composite else "")
                    + f" type='{self.id(ptype)}' association='{self.id(assoc)}'>{mult}</ownedAttribute>")
                self.nodes[pkg].children.append(
                    f"<packagedElement xmi:type='uml:Association' xmi:id='{self.id(assoc)}'>"
                    f"<memberEnd xmi:idref='{self.id(pk)}'/><memberEnd xmi:idref='{self.id(assoc)}_end'/>"
                    f"<ownedEnd xmi:type='uml:Property' xmi:id='{self.id(assoc)}_end' type='{self.id(key)}' "
                    f"association='{self.id(assoc)}'/></packagedElement>")
                self.parts[key].append((pk, pname, ptype))
                self.names[pk], self.kinds[pk] = pname, "Property"
                self.ends[assoc], self.kinds[assoc] = (key, ptype), "Association"
        self.ports[key] = {}
        for pname, ptype in ports:
            pk = f"{key}__port_{slug(pname)}"
            node.children.append(f"<ownedAttribute xmi:type='uml:Port' xmi:id='{self.id(pk)}' name={quoteattr(pname)}"
                                 + (f" type='{self.id(ptype)}'" if ptype else "") + " aggregation='composite'/>")
            self.apply("sysml", "ProxyPort", pk, base="Port")
            self.ports[key][pname], self.names[pk], self.kinds[pk] = pk, pname, "Port"
        if stereotype:
            self.apply("sysml", "InterfaceBlock" if interface else stereotype, key)
        return key

    def connector(self, block: str, name: str | None, end1: tuple[str, str | None], end2: tuple[str, str | None],
                  items: list[str] = ()) -> str:
        """A connector inside `block` between (part name, port name or None) ends; `items` are the
        keys of what flows along it (an «ItemFlow» from the first end to the second)."""
        ck = f"{block}__c{len(self.connectors.setdefault(block, []))}"
        ends, roles = [], []
        for i, (part, port) in enumerate((end1, end2)):
            part_key = next(k for k, n, _ in self.parts[block] if n == part)
            ptype = next(t for k, n, t in self.parts[block] if n == part)
            role = self.ports[ptype][port] if port else part_key
            roles.append(role)
            ends.append(f"<end xmi:type='uml:ConnectorEnd' xmi:id='{self.id(ck)}_e{i}' role='{self.id(role)}'"
                        + (f" partWithPort='{self.id(part_key)}'" if port else "") + "/>")
        self.nodes[block].children.append(
            f"<ownedConnector xmi:type='uml:Connector' xmi:id='{self.id(ck)}'"
            + (f" name={quoteattr(name)}" if name else "") + ">" + "".join(ends) + "</ownedConnector>")
        self.connectors[block].append(ck)
        self.names[ck], self.kinds[ck] = name or "", "Connector"
        self.ends[ck] = (end1[0], end2[0])  # part names: resolved to views by the IBD
        if items:
            fk = f"{ck}_flow"
            owner_pkg = self._owner_package(block)
            self.nodes[owner_pkg].children.append(
                f"<packagedElement xmi:type='uml:InformationFlow' xmi:id='{self.id(fk)}'>"
                + "".join(f"<conveyed xmi:idref='{self.id(i)}'/>" for i in items)
                + f"<informationSource xmi:idref='{self.id(roles[0])}'/><informationTarget xmi:idref='{self.id(roles[1])}'/>"
                + f"<realizingConnector xmi:idref='{self.id(ck)}'/></packagedElement>")
            self.apply("sysml", "ItemFlow", fk, base="InformationFlow")
        return ck

    def _owner_package(self, key: str) -> str:
        for k, node in self.nodes.items():
            if self.kinds.get(k) in ("Package", "Model") and self.nodes[key] in node.children:
                return k
        raise KeyError(key)

    def instance(self, key: str, name: str, classifier: str, pkg: str, slots: dict[str, object],
                 doc: str | None = None) -> str:
        """An instance of a block, with values for its value properties (by name)."""
        self._add(key, pkg, f"<packagedElement xmi:type='uml:InstanceSpecification' xmi:id='{self.id(key)}' "
                            f"name={quoteattr(name)} classifier='{self.id(classifier)}'>", "</packagedElement>",
                  name, "InstanceSpecification")
        self._doc(key, doc)
        for i, (prop, value) in enumerate(slots.items()):
            feature = self.values[classifier][prop]
            self.nodes[key].children.append(
                f"<slot xmi:type='uml:Slot' xmi:id='{self.id(key)}__s{i}' definingFeature='{self.id(feature)}'>"
                + _literal(f"{self.id(key)}__s{i}v", value, "value") + "</slot>")
        return key

    def note(self, key: str, text: str, pkg: str, annotates: list[str] = ()) -> str:
        """A free-standing comment (a note on a diagram), annotating some elements."""
        self.nodes[pkg].children.append(
            f"<ownedComment xmi:type='uml:Comment' xmi:id='{self.id(key)}' body={quoteattr(text)}>"
            + "".join(f"<annotatedElement xmi:idref='{self.id(a)}'/>" for a in annotates) + "</ownedComment>")
        self.names[key], self.kinds[key] = "", "Comment"
        return key

    def constraint_block(self, key: str, name: str, pkg: str, expression: str, params: list[tuple[str, str | None]],
                         doc: str | None = None) -> str:
        """A constraint block: its parameters (name, value type key) and one constraint."""
        self.block(key, name, pkg, doc, values=[(n, t, None) for n, t in params], stereotype="ConstraintBlock")
        self.nodes[key].children.append(
            f"<ownedRule xmi:type='uml:Constraint' xmi:id='{self.id(key)}__rule' name={quoteattr(name)}>"
            f"<constrainedElement xmi:idref='{self.id(key)}'/>"
            f"<specification xmi:type='uml:OpaqueExpression' xmi:id='{self.id(key)}__spec'>"
            f"<body>{escape(expression)}</body><language>English</language></specification></ownedRule>")
        return key

    # -- requirements and relationships ----------------------------------------------------------
    def requirement(self, key: str, rid: str | None, name: str | None, text: str, pkg: str, *,
                    profile: str = "sysml", stereotype: str = "Requirement", doc: str | None = None,
                    **tags: object) -> str:
        """A requirement; with no name, as imported from DOORS (name it by its text)."""
        self._add(key, pkg, f"<packagedElement xmi:type='uml:Class' xmi:id='{self.id(key)}'"
                            + (f" name={quoteattr(name)}" if name else "") + ">", "</packagedElement>",
                  name or "", "Class")
        self._doc(key, doc)
        self.apply(profile, stereotype, key, Id=rid, Text=text, **tags)
        return key

    def relate(self, kind: str, source: str, target: str, pkg: str, name: str | None = None) -> str:
        """A directed relationship: a stereotyped abstraction (satisfy, deriveReqt, verify,
        allocate, refine, trace, copy), or a plain dependency (`dependency`), from source to target."""
        key = f"{kind}__{source}__{target}"
        if kind == "dependency":
            head = f"<packagedElement xmi:type='uml:Dependency' xmi:id='{self.id(key)}'"
        else:
            head = f"<packagedElement xmi:type='uml:Abstraction' xmi:id='{self.id(key)}'"
        self._add(key, pkg, head + (f" name={quoteattr(name)}" if name else "")
                  + f" client='{self.id(source)}' supplier='{self.id(target)}'>", "</packagedElement>",
                  name or "", "Dependency" if kind == "dependency" else "Abstraction")
        if kind in RELATION_STEREOTYPES:
            profile, st = RELATION_STEREOTYPES[kind]
            self.apply(profile, st, key, base="Abstraction")
        self.ends[key] = (source, target)
        return key

    # -- behaviour -------------------------------------------------------------------------------
    def activity(self, key: str, name: str, owner: str, doc: str | None, nodes: list[tuple[str, str, str]],
                 edges: list[tuple], *, test_case: bool = False) -> str:
        """An activity. `nodes`: (key, kind, name), kinds as UML's (OpaqueAction, CallBehaviorAction,
        InitialNode, ActivityFinalNode, DecisionNode, MergeNode, ForkNode, JoinNode). `edges`:
        (source, target) or (source, target, guard). `owner`: a package, or a block (whose
        behaviour it is)."""
        role = "ownedBehavior" if self.kinds[owner] == "Class" else "packagedElement"
        self._add(key, owner, f"<{role} xmi:type='uml:Activity' xmi:id='{self.id(key)}' name={quoteattr(name)}>",
                  f"</{role}>", name, "Activity")
        self._doc(key, doc)
        node = self.nodes[key]
        for nk, kind, nname in nodes:
            node.children.append(f"<node xmi:type='uml:{kind}' xmi:id='{self.id(nk)}'"
                                 + (f" name={quoteattr(nname)}" if nname else "") + "/>")
            self.names[nk], self.kinds[nk] = nname, kind
        self.members[key] = [nk for nk, _, _ in nodes]
        self.flows[key] = []
        for e in edges:
            s, t = e[:2]
            ek = f"{key}__f_{s}_{t}"
            guard = (f"<guard xmi:type='uml:OpaqueExpression' xmi:id='{self.id(ek)}_g'><body>{escape(e[2])}</body>"
                     "</guard>" if len(e) > 2 and e[2] else "")
            node.children.append(f"<edge xmi:type='uml:ControlFlow' xmi:id='{self.id(ek)}' source='{self.id(s)}' "
                                 f"target='{self.id(t)}'>{guard}</edge>")
            self.flows[key].append((ek, s, t))
            self.ends[ek], self.kinds[ek] = (s, t), "ControlFlow"
        if test_case:
            self.apply("sysml", "TestCase", key, base="Behavior")
        return key

    def state_machine(self, key: str, name: str, owner: str, doc: str | None, states: list[tuple],
                      transitions: list[tuple]) -> str:
        """A state machine owned by a block. `states`: (key, name) for a state, or (key, name, do)
        with what it does; keys `init` and `final` (any prefix) make the initial and final
        vertices. `transitions`: (source, target, trigger signal key or None, guard or None)."""
        self._add(key, owner, f"<ownedBehavior xmi:type='uml:StateMachine' xmi:id='{self.id(key)}' "
                              f"name={quoteattr(name)}>", "</ownedBehavior>", name, "StateMachine")
        self._doc(key, doc)
        region = _Node(f"<region xmi:type='uml:Region' xmi:id='{self.id(key)}__r'>", "</region>")
        self.nodes[key].children.append(region)
        for st in states:
            sk, sname = st[:2]
            if sk.endswith("init"):
                region.children.append(f"<subvertex xmi:type='uml:Pseudostate' xmi:id='{self.id(sk)}' kind='initial'/>")
                self.kinds[sk] = "Pseudostate"
            elif sk.endswith("final"):
                region.children.append(f"<subvertex xmi:type='uml:FinalState' xmi:id='{self.id(sk)}'/>")
                self.kinds[sk] = "FinalState"
            else:
                do = (f"<doActivity xmi:type='uml:OpaqueBehavior' xmi:id='{self.id(sk)}__do' name={quoteattr(st[2])}/>"
                      if len(st) > 2 else "")
                region.children.append(f"<subvertex xmi:type='uml:State' xmi:id='{self.id(sk)}' "
                                       f"name={quoteattr(sname)}>{do}</subvertex>")
                self.kinds[sk] = "State"
            self.names[sk] = sname
        self.members[key] = [st[0] for st in states]
        self.flows[key] = []
        for i, (s, t, trigger, guard) in enumerate(transitions):
            tk = f"{key}__t{i}"
            body = ""
            if trigger:
                ev = f"{trigger}__event"
                if ev not in self.names:
                    self.nodes[self._owner_package(trigger)].children.append(  # unnamed, as Cameo makes them
                        f"<packagedElement xmi:type='uml:SignalEvent' xmi:id='{self.id(ev)}' signal='{self.id(trigger)}'/>")
                    self.names[ev], self.kinds[ev] = "", "SignalEvent"
                body += f"<trigger xmi:type='uml:Trigger' xmi:id='{self.id(tk)}_tr' event='{self.id(ev)}'/>"
            if guard:
                body += (f"<guard xmi:type='uml:Constraint' xmi:id='{self.id(tk)}_g'>"
                         f"<specification xmi:type='uml:OpaqueExpression' xmi:id='{self.id(tk)}_gs'>"
                         f"<body>{escape(guard)}</body></specification></guard>")
            region.children.append(f"<transition xmi:type='uml:Transition' xmi:id='{self.id(tk)}' "
                                   f"source='{self.id(s)}' target='{self.id(t)}'>{body}</transition>")
            self.flows[key].append((tk, s, t))
            self.ends[tk], self.kinds[tk] = (s, t), "Transition"
        return key

    # -- diagrams --------------------------------------------------------------------------------
    def _diagram(self, key: str, name: str, kind: str, owner: str, shapes: list[_Shape],
                 paths: list[tuple[str, str, str, str]]) -> str:
        stream = f"BINARY-{self.prefix}-{slug(key)}"
        self.nodes[owner].children.append(
            "<xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>"
            f"<ownedDiagram xmi:type='uml:Diagram' xmi:id='{self.id(key)}' name={quoteattr(name)} "
            f"ownerOfDiagram='{self.id(owner)}'>"
            "<xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>"
            "<diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0' "
            f"type={quoteattr(kind)} umlType={quoteattr(DIAGRAM_TYPES[kind])}>"
            f"<diagramContents><binaryObject streamContentID='{stream}'/></diagramContents>"
            "</diagram:DiagramRepresentationObject></diagramRepresentation></xmi:Extension>"
            "</ownedDiagram></modelExtension></xmi:Extension>")
        self.names[key], self.kinds[key] = name, "Diagram"
        centre = {}

        def emit(s: _Shape, indent: str) -> list[str]:
            x, y, w, h = s.rect
            centre[s.view] = (x + w // 2, y + h // 2)
            out = [(f"{indent}<mdElement elementClass='{s.cls}' xmi:id='{s.view}'>"
                    f"<elementID xmi:idref='{self.id(s.element)}'/><geometry>{x}, {y}, {w}, {h}</geometry>")]
            if s.nested:
                out.append(f"{indent} <mdOwnedViews>")
                for n in s.nested:
                    out += emit(n, indent + "  ")
                out.append(f"{indent} </mdOwnedViews>")
            out.append(f"{indent}</mdElement>")
            return out

        lines = ["<?xml version='1.0' encoding='UTF-8' standalone='no'?>", "<mdOwnedViews>"]
        for s in shapes:
            lines += emit(s, " ")
        for i, (cls, el, src, tgt) in enumerate(paths):  # Cameo stores a path's target as its first end
            if src not in centre or tgt not in centre:
                continue
            (x1, y1), (x2, y2) = centre[tgt], centre[src]
            lines.append(f" <mdElement elementClass='{cls}' xmi:id='{self.prefix}-{slug(key)}-p{i}'>"
                         f"<elementID xmi:idref='{self.id(el)}'/><linkFirstEndID xmi:idref='{tgt}'/>"
                         f"<linkSecondEndID xmi:idref='{src}'/><geometry>{x1}, {y1}; {x2}, {y2}; </geometry></mdElement>")
        self.layouts[stream] = "\n".join(lines + ["</mdOwnedViews>", ""])
        return key

    def _grid(self, key: str, elements: list[str], cols: int | None = None, w: int = 170, h: int = 70,
              cls: dict[str, str] | None = None) -> list[_Shape]:
        cols = cols or max(1, math.ceil(math.sqrt(len(elements) * 1.6)))
        shape_cls = {"Class": "Class", "Package": "Package", "DataType": "DataType", "Comment": "Note",
                     "InstanceSpecification": "InstanceSpecification", "Activity": "Activity",
                     "Signal": "Signal", "StateMachine": "StateMachine"}
        out = []
        for i, el in enumerate(elements):
            c = (cls or {}).get(el) or shape_cls.get(self.kinds[el], self.kinds[el])
            out.append(_Shape(f"{self.prefix}-{slug(key)}-v{i}", c, el,
                              (40 + (i % cols) * (w + 60), 40 + (i // cols) * (h + 70), w, h)))
        return out

    def diagram(self, key: str, name: str, kind: str, owner: str, elements: list[str], cols: int | None = None) -> str:
        """A diagram of `elements` on a grid, with every relationship among them (relations,
        compositions, generalizations) drawn."""
        shapes = self._grid(key, elements, cols)
        view = {s.element: s.view for s in shapes}
        paths = []
        for rel, (s, t) in self.ends.items():
            if s in view and t in view and self.kinds.get(rel) in ("Abstraction", "Dependency", "Association",
                                                                   "Generalization"):
                paths.append((self.kinds[rel], rel, view[s], view[t]))
        return self._diagram(key, name, kind, owner, shapes, paths)

    def behavior_diagram(self, key: str, name: str, behavior: str, cols: int = 4) -> str:
        """An activity or state machine diagram of every node and flow of `behavior`."""
        kind = "SysML Activity Diagram" if self.kinds[behavior] == "Activity" else "SysML State Machine Diagram"
        node_cls = {"InitialNode": "PseudoNode", "ActivityFinalNode": "PseudoNode", "FlowFinalNode": "PseudoNode",
                    "DecisionNode": "Decision", "MergeNode": "Decision", "ForkNode": "Bar", "JoinNode": "Bar",
                    "Pseudostate": "PseudoState", "FinalState": "PseudoState"}
        members = self.members[behavior]
        shapes = self._grid(key, members, cols, w=150, h=50,
                            cls={m: node_cls.get(self.kinds[m], self.kinds[m]) for m in members})
        view = {s.element: s.view for s in shapes}
        cls = "ControlFlow" if kind == "SysML Activity Diagram" else "Transition"
        paths = [(cls, ek, view[s], view[t]) for ek, s, t in self.flows[behavior]]
        return self._diagram(key, name, kind, behavior, shapes, paths)

    def ibd(self, key: str, name: str, block: str) -> str:
        """An internal block diagram of `block`: its parts, the ports its connectors use, and the
        connectors."""
        used: dict[str, set[str]] = {}
        for ck in self.connectors.get(block, []):
            for part in self.ends[ck]:
                used.setdefault(part, set())
        shapes, view = [], {}
        parts = self.parts[block]
        cols = max(1, math.ceil(math.sqrt(len(parts) * 1.6)))
        for i, (pk, pname, ptype) in enumerate(parts):
            x, y = 60 + (i % cols) * 280, 60 + (i // cols) * 180
            nested = [_Shape(f"{self.prefix}-{slug(key)}-v{i}-{j}", "Port", port_key, (x + 190, y + 10 + 22 * j, 20, 20))
                      for j, port_key in enumerate(self.ports.get(ptype, {}).values())]
            shapes.append(_Shape(f"{self.prefix}-{slug(key)}-v{i}", "Part", pk, (x, y, 200, 110), nested))
            view[pname] = shapes[-1].view
        paths = [("Connector", ck, view[self.ends[ck][0]], view[self.ends[ck][1]])
                 for ck in self.connectors.get(block, [])]
        return self._diagram(key, name, "SysML Internal Block Diagram", block, shapes, paths)

    # -- questions -------------------------------------------------------------------------------
    def ask(self, qid: str, category: str, difficulty: str, literal: str, paraphrase: str | None,
            answers: list[str], related: list[str] = (), evidence: str | list[str] | dict[str, str | list[str]] = "",
            ) -> None:
        """A fact, asked literally and (if given) as a paraphrase. `answers`: the keys of the
        elements whose chunks hold it; `evidence`: the phrase (or alternatives) they hold, or, where
        each says it differently, a phrase per answering element (a relationship reads from
        either end: "is allocated to PLC-400", "Post-Contact Chlorine Analyzer is allocated to this")."""
        for k in [*answers, *related, *(evidence if isinstance(evidence, dict) else ())]:
            if k not in self.names:
                raise KeyError(f"{self.prefix} {qid}: no element {k!r}")
        by_element = {}
        if isinstance(evidence, dict):
            by_element = {self.id(k): [v] if isinstance(v, str) else list(v) for k, v in evidence.items()}
            evidence = []
        for style, text in (("literal", literal), ("paraphrase", paraphrase)):
            if text:
                self._questions.append({
                    "id": f"{self.prefix}-{qid}-{style}", "rule": "fact", "fact": f"{self.prefix}-{qid}", "style": style,
                    "category": category, "difficulty": difficulty, "question": text,
                    "answers": [self.id(a) for a in answers], "related": [self.id(r) for r in related],
                    "evidence": [evidence] if isinstance(evidence, str) else list(evidence),
                    "evidence_by_element": by_element, "prefix": f"_{self.prefix}_", "project_name": self.name})

    # -- output ----------------------------------------------------------------------------------
    def xmi(self) -> str:
        ns = " ".join(f"xmlns:{k}='{v}'" for k, v in self.namespaces.items())
        return ("<?xml version='1.0' encoding='UTF-8'?>\n"
                f"<xmi:XMI {ns}>\n"
                " <xmi:Documentation><xmi:exporter>MagicDraw UML</xmi:exporter>"
                "<xmi:exporterVersion>2024x</xmi:exporterVersion></xmi:Documentation>\n"
                + self.model.render() + "\n " + "\n ".join(self.applications) + "\n</xmi:XMI>\n")

    def mdzip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            def entry(name: str) -> zipfile.ZipInfo:  # fixed times: the same bytes, so the same token
                return zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            z.writestr(entry("com.nomagic.magicdraw.uml_model.model"), self.xmi())
            for stream, text in sorted(self.layouts.items()):
                z.writestr(entry(stream), text)
            z.writestr(entry("Records.properties"), "#Compatibility entry\n")
        return buf.getvalue()

    @property
    def path(self) -> str:
        """The file's path among the fictional projects."""
        return f"{self.folder}/{self.file_name}" if self.folder else self.file_name

    def questions(self) -> list[dict]:
        token = "sha256:" + hashlib.sha256(self.mdzip()).hexdigest()
        return [{**q, "project": token} for q in self._questions]

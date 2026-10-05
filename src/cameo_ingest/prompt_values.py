"""The values of every LLM request, built beside the template they fill (AR-009): one function
per template, returning the values, the notes for the request log, and what was cut, if
anything. The limits are the templates' (`prompts`), and every sentence a request adds comes
from its template's fragments, so that no wording reaches the model outside a version.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import diagram_text as dt
from . import semantics as sem
from .diagram_graph import DiagramGraph
from .model import Diagram, Element, ModelIndex
from .partition import Partition
from .prompts import CONTEXT_CHARS, CURRENT, DIAGRAM_ITEMS, DIGEST_CHARS, GUIDE, OWN_CHARS, PART_CHARS, Template
from .sketch import conventions
from .text import one_line, plural


@dataclass
class Values:
    values: dict[str, str]
    notes: dict[str, Any] = field(default_factory=dict)  # for the request log
    cut: str = ""  # what was cut, for the run's report; empty when nothing was


def diagram_name(d: Diagram) -> str:
    return f"{d.name} ({d.diagram_type or 'unknown type'})"


def guide(template: Template, found: set[str]) -> str:
    """The template's sentences on reading a sketch, for the conventions `found` in it (plan SK):
    empty when there are none, else a paragraph after the text before it."""
    names = [k for k, _ in template.fragments if k in found and k in dict(GUIDE)]
    return "\n\n" + "\n".join([template.fragment("guide"), *map(template.fragment, names)]) if names else ""


def diagram_description(ix: ModelIndex, g: DiagramGraph, d: Diagram) -> Values:
    nodes, edges = dt.describe(ix, g)
    out = Values({"DIAGRAM": diagram_name(d), "LEGEND": "\n".join(nodes[:DIAGRAM_ITEMS]),
                  "CONNECTIONS": "\n".join(edges[:DIAGRAM_ITEMS]) or "(none)", "CUT_NOTE": "",
                  "GUIDE": guide(CURRENT["diagram-description"], conventions(g))})
    if max(len(nodes), len(edges)) > DIAGRAM_ITEMS:
        out.values["CUT_NOTE"] = CURRENT["diagram-description"].fragment(
            "cut", limit=DIAGRAM_ITEMS, shapes=len(nodes), connections=len(edges))
        out.notes["truncated"] = {"shapes": len(nodes), "connections": len(edges), "limit": DIAGRAM_ITEMS}
        out.cut = f"{len(nodes)} shapes, {len(edges)} connections; the first {DIAGRAM_ITEMS} of each sent"
    return out


def module_description(ix: ModelIndex, part: Partition, num: int, d: Diagram) -> Values:
    legend, lines, boundary = dt.module_lists(ix, part, num)
    m = part.modules[num - 1]
    return Values({"DIAGRAM": diagram_name(d), "MODULE": f"M{num} of {len(part.modules)}", "LEGEND": "\n".join(legend),
                   "CONNECTIONS": "\n".join(lines) or "(none)", "BOUNDARY": "\n".join(boundary) or "(none)",
                   "GUIDE": guide(CURRENT["module-description"], conventions(part.graph, set(m.shapes)))},
                  {"module": f"M{num} of {len(part.modules)}"})


def diagram_synthesis(ix: ModelIndex, part: Partition, d: Diagram,
                      texts: list[str | None]) -> Values:
    """From the modules' descriptions (`texts`, None for a module that got no answer)."""
    modules = "\n\n".join(f"M{m.num} ({len(m.shapes)} shapes): {text or '(not described)'}"
                          for m, text in zip(part.modules, texts, strict=True))
    missing = sum(t is None for t in texts)
    return Values({"DIAGRAM": diagram_name(d), "MODULES": modules,
                   "CROSSING": "\n".join(dt.crossing_lines(ix, part)) or "(none)"},
                  {"modules": len(part.modules), **({"undescribed": missing} if missing else {})})


def image_description() -> Values:
    return Values({})


def package_summary(text: str) -> Values:
    """A package small enough for one request (at most `SUMMARY_CHARS`)."""
    return Values({"PACKAGE_TEXT": text})


def module_summary(package: str, k: int, n: int, body: str, limit: int = PART_CHARS[1]) -> Values:
    """Part `k` of `n` of a large package. A body over `limit` is cut, with a note; parts are
    made to fit (plan TC-01), so that would be a fault."""
    out = Values({"CUT_NOTE": "", "PACKAGE": package, "PART": f"{k} of {n}", "SECTIONS": body[:limit]},
                 {"part": f"{k} of {n}"})
    if len(body) > limit:
        out.values["CUT_NOTE"] = CURRENT["module-summary"].fragment("cut", limit=limit, length=len(body))
        out.notes["truncated"] = {"characters": len(body), "limit": limit}
        out.cut = f"part {k}: {len(body):,} characters; the first {limit:,} sent"
    return out


Level = list[tuple[tuple[int, int], str | None]]  # (first part, last part), summary


def package_synthesis(package: str, sizes: list[int], own: str, run: Level, whole: bool) -> Values:
    """Over `run` of the summaries of a package whose parts have `sizes` elements: the whole
    package, or a run of its parts when there are many."""
    a, b = run[0][0][0], run[-1][0][1]
    summaries = "\n\n".join(
        (f"Part {x} ({plural(sizes[x - 1], 'element')}): " if x == y else f"Parts {x} to {y}: ")
        + (text or "(not summarized)") for (x, y), text in run)
    scope = "the whole package" if whole else f"parts {a} to {b} of {len(sizes)}"
    cut = (CURRENT["package-synthesis"].fragment("cut", limit=OWN_CHARS, length=len(own))
           if len(own) > OWN_CHARS else "")
    return Values({"SCOPE": scope, "CUT_NOTE": cut, "PACKAGE": package, "PACKAGE_TEXT": own[:OWN_CHARS],
                   "SUMMARIES": summaries}, {"parts": len(sizes), "scope": scope})


def instances_summary(ix: ModelIndex, package: str, own: str, sections: list[Element], texts: list[str]) -> Values:
    """A package made mostly of instance specifications, described by a digest of them rather
    than in full (FU-022)."""
    instances = [e for e in sections if e.kind == "InstanceSpecification"]

    def classifier(el_id: str) -> str:
        el = ix.elements.get(el_id)
        return ", ".join(sem.label(ix, c) for c in sem.refs(el, "classifier")) if el else ""

    def name(el_id: str) -> str:
        """Generated names run long ("Scenario.aPS Mission Logical.aps operational blackbox.peas…"):
        their ends tell them apart."""
        label = one_line(sem.label(ix, el_id))
        return label if len(label) <= 80 else "…" + label[-79:]

    slots: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))  # classifier -> feature -> values
    by_classifier: dict[str, list[Element]] = defaultdict(list)
    referred: set[str] = set()
    for e in instances:
        cls = classifier(e.id) or "(no classifier)"
        by_classifier[cls].append(e)
        for slot in sem.children(ix, e):
            if slot.kind != "Slot":
                continue
            feature = next((sem.label(ix, f) for f in sem.refs(slot, "definingFeature")), "(unnamed)")
            for v in sem.children(ix, slot):
                targets = sem.refs(v, "instance")
                referred.update(targets)
                target = ix.elements.get(targets[0]) if targets else None
                if target is not None and target.kind == "InstanceSpecification" and classifier(target.id):
                    value = f"an instance of {classifier(target.id)}"  # say what it is, not its long name
                elif targets:  # an enumeration literal, say
                    value = name(targets[0])
                else:
                    value = one_line(sem.value_text(ix, v) or v.kind)[:60]
                slots[cls][feature].append(value)
    top = [e for e in instances if e.id not in referred]
    lines = [f"{len(instances):,} instance specifications of {plural(len(by_classifier), 'classifier')}.",
             "Top-level instances: " + "; ".join(name(e.id) for e in top[:10]) + ("; ..." if len(top) > 10 else "")]
    for cls, members in sorted(by_classifier.items(), key=lambda kv: -len(kv[1]))[:40]:
        names = "; ".join(name(e.id) for e in members[:3])
        lines.append(f"- {cls}: {plural(len(members), 'instance')}, such as {names}")
        for feature, values in sorted(slots[cls].items(), key=lambda kv: -len(kv[1]))[:8]:
            shown = ", ".join(dict.fromkeys(values))[:200]
            lines.append(f"  - slot {feature}, set {plural(len(values), 'time')}: {shown}")
    digest = "\n".join(lines)
    if len(digest) > DIGEST_CHARS[0]:
        digest = digest[:DIGEST_CHARS[0]] + CURRENT["instances-summary"].fragment("cut")
    others = "\n".join(text for e, text in zip(sections, texts, strict=True) if e.kind != "InstanceSpecification")
    return Values({"PACKAGE": package, "PACKAGE_TEXT": own[:OWN_CHARS], "DIGEST": digest,
                   "OTHERS": others[:DIGEST_CHARS[1]] or "(none)"},
                  {"digest": {"instances": len(instances), "elements": len(sections)}})


# -- Context (plan GS): what the model says around a package or a diagram ----------------------
def _cut(text: str, limit: int) -> str:
    text = one_line(text)
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def _first_sentence(text: str, limit: int) -> str:
    text = one_line(text)
    m = re.search(r"(?<=[.!?])\s", text)
    return _cut(text[:m.start()] if m else text, limit)


def package_context(ix: ModelIndex, pkg_id: str) -> str:
    """Where the package sits, and what it refers to: the model and each package around it, with
    what their documentation says first; then the documented elements outside it that its
    elements refer to most, with the first sentence of theirs."""
    chain = []
    el = ix.elements[pkg_id]
    while el.owner in ix.elements:
        el = ix.elements[el.owner]  # type: ignore[index]
        chain.append(el)
    lines = []
    for el in reversed(chain):
        doc = _cut(sem.documentation(ix, el), CONTEXT_CHARS[0])
        lines.append(f"{'The model' if el is chain[-1] else 'Within'} {el.name or '(unnamed)'}" + (f": {doc}" if doc else ""))
    inside: set[str] = set()
    todo = [pkg_id]
    while todo:
        e = ix.elements[todo.pop()]
        inside.add(e.id)
        todo += [c for c in e.children if c in ix.elements]
    cited: defaultdict[str, int] = defaultdict(int)
    for e in inside:
        for _, target in ix.elements[e].refs:
            if target in ix.elements and target not in inside:
                cited[target] += 1
    refs = []
    for target, _ in sorted(cited.items(), key=lambda kv: (-kv[1], kv[0])):
        t = ix.elements[target]
        doc = _first_sentence(sem.documentation(ix, t), CONTEXT_CHARS[1])
        if doc and t.name:
            refs.append(f"- {t.kind} {t.name}: {doc}")
        if len(refs) == 10:
            break
    if refs:
        lines += ["It refers to:", *refs]
    return _lines(lines, CONTEXT_CHARS[2]) or "(none)"


def _lines(lines: list[str], limit: int) -> str:
    """As many whole lines as fit in `limit` characters."""
    out, size = [], 0
    for line in lines:
        if size + len(line) + 1 > limit:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def diagram_context(ix: ModelIndex, g: DiagramGraph | None, d: Diagram) -> str:
    """The diagram's context element, and each shape's element, by what the model says of them:
    the first sentence of its documentation, and a state's entry, do and exit behaviors."""
    lines = []
    ctx = ix.elements.get(d.owner or "")
    if ctx is not None:
        doc = _first_sentence(sem.documentation(ix, ctx), CONTEXT_CHARS[1])
        lines.append(f"Context, {ctx.kind} {ctx.name or '(unnamed)'}" + (f": {doc}" if doc else ""))
    for n in g.nodes if g is not None else []:
        el = ix.elements.get(n.view.element or "")
        if el is None:
            continue
        doc = _first_sentence(sem.documentation(ix, el), CONTEXT_CHARS[1])
        behaviors = [f"{role.removesuffix('Activity')}: {b.name}" for role in ("entry", "doActivity", "exit")
                     for b in sem.children(ix, el, role) if b.name]
        if doc or behaviors:
            lines.append(f"- [{n.num}] {one_line(n.label)}" + (f": {doc}" if doc else "")
                         + "".join(f"; {b}" for b in behaviors))
    return _lines(lines, CONTEXT_CHARS[2]) or "(none)"


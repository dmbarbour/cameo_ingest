"""The values of every LLM request, built beside the template they fill (AR-009): one function
per template, returning the values, the notes for the request log, and what was cut, if
anything. The limits are the templates' (`prompts`), and every sentence a request adds comes
from its template's fragments, so that no wording reaches the model outside a version.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import diagram_text as dt
from . import semantics as sem
from .diagram_graph import DiagramGraph
from .model import Diagram, Element, ModelIndex
from .partition import Partition
from .prompts import CURRENT, DIAGRAM_ITEMS, DIGEST_CHARS, GUIDE, OWN_CHARS, PART_CHARS, Template
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


def module_summary(package: str, k: int, n: int, body: str) -> Values:
    """Part `k` of `n` of a large package."""
    out = Values({"CUT_NOTE": "", "PACKAGE": package, "PART": f"{k} of {n}", "SECTIONS": body[:PART_CHARS[1]]},
                 {"part": f"{k} of {n}"})
    if len(body) > PART_CHARS[1]:
        out.values["CUT_NOTE"] = CURRENT["module-summary"].fragment("cut", limit=PART_CHARS[1], length=len(body))
        out.notes["truncated"] = {"characters": len(body), "limit": PART_CHARS[1]}
        out.cut = f"part {k}: {len(body):,} characters; the first {PART_CHARS[1]:,} sent"
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

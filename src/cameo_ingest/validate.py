"""Validating a vision model's calibration on the tree's own sketches (plan VA-05).

The eye charts measure what a model reads on cards made for it. This asks what it reads on the
tree's own diagrams, drawn at the sizes the run will use: a sample of small diagrams, medium
ones and modules of large ones, from a few of the tree's projects, each scored against the
diagram's own truth (the names drawn on its shapes, its connections and their directions).

It measures what the model can see. A description gets every name and connection as text too,
so it should do better than this; a low score says what a description may get wrong.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from . import eyechart as ec
from . import sketch
from .archive import discover
from .config import IMAGE_PIXELS, TreeSettings
from .diagram_graph import DiagramGraph
from .llm import EnrichmentSession
from .pipeline import load_layouts, parse_project
from .progress import QUIET, Progress
from .prompts import Slot, Template
from .provenance import ContentInfo
from .sketch import SketchStyle
from .state import State
from .view import ProjectView

TEMPLATE = Template(  # outside prompts.CURRENT: validation changes no project's options
    id="eye-sketch", version=1,
    purpose="One of the tree's own sketches, to measure what the vision model reads on it (plan VA); scored, "
            "not stored.",
    text=("The image is a sketch of a diagram from a systems engineering model: shapes, each tagged with a number "
          "in a grey box and showing its name, joined by connections; an arrowhead marks where a directed "
          "connection ends. A name too long for its shape is cut short with '…'. Shapes drawn faded are context: "
          "leave them out, except as the ends of connections. List every numbered shape with its name as written, "
          "and every connection by the numbers of the shapes it joins: from the shape it starts at to the shape "
          "its arrowhead points to, either way round for a connection without one.\n"
          + ec.JSON_ONLY + '{"shapes": [{"number": 3, "name": "Battery"}], "connections": [{"from": 3, "to": 7}]}'),
    slots=(Slot("SKETCH", "image", "one of the tree's sketches, drawn at the calibrated sizes"),),
    image_first=True,
)
SMALL = 9  # shapes: a small diagram; above it and up to the modules' threshold, medium
PER_STRATUM = 4
MAX_PROJECTS = 4  # parsed for the sample
MAX_BYTES = 30_000_000  # larger projects are left out of the sample: parsing them takes too long
PASS = 0.9  # below it, a warning


@dataclass
class Sketch:
    key: str  # project token, diagram, module
    project: str
    diagram: str
    kind: str  # the diagram's type
    stratum: str  # small, medium, modules
    png: bytes
    truth: dict[str, Any]  # {"shapes": {number: name as drawn}, "links": [[from, to, directed]]}


def strata(large: int) -> dict[str, str]:
    return {"small": f"small diagrams (up to {SMALL} shapes)",
            "medium": f"medium diagrams ({SMALL + 1} to {large} shapes)",
            "modules": "modules of large diagrams"}


def _project(state: State, sha: str) -> Any | None:
    where = next((s for s in state.sightings(sha) if s["input_status"] == "done"), None)
    if where is None or not Path(where["path"]).is_file():
        return None
    path = Path(where["path"])
    return next((p for p in discover(path.read_bytes(), path.name) if p.sha256 == sha), None)


def _truth(g: DiagramGraph, shapes: dict[int, str], ends: set[int]) -> dict[str, Any]:
    """The shapes as drawn, and the connections among shapes in `ends` that touch a drawn one."""
    links = []
    for lk in g.links:
        a = g.node_of.get(lk.source.view_id or "") if lk.source is not None else None
        b = g.node_of.get(lk.target.view_id or "") if lk.target is not None else None
        if a is None or b is None or a.num == b.num or {a.num, b.num} - ends or not {a.num, b.num} & set(shapes):
            continue
        links.append([a.num, b.num, lk.directed])
    return {"shapes": {str(n): t for n, t in sorted(shapes.items())}, "links": links}


def sample(state: State, settings: TreeSettings, progress: Progress = QUIET) -> list[Sketch]:
    """Up to PER_STRATUM sketches of each stratum, from up to MAX_PROJECTS of the tree's projects,
    drawn at `settings`' sizes. Within a stratum, the commonest diagram types come first."""
    pixels = settings.image_pixels or IMAGE_PIXELS
    style, modules = SketchStyle(*settings.sketch), settings.modules
    rows = [r for r in state.catalog() if r["status"] != "removed"]
    sizes = {r["sha256"]: state.content(r["sha256"])["size"] for r in rows}
    order = sorted((r for r in rows if sizes[r["sha256"]] <= MAX_BYTES),
                   key=lambda r: hashlib.sha256(r["sha256"].encode()).hexdigest())
    pool: dict[str, list[Sketch]] = defaultdict(list)
    kinds: dict[str, Counter[str]] = defaultdict(Counter)
    parsed = 0
    for r in order:
        if parsed >= MAX_PROJECTS:
            break
        project = _project(state, r["sha256"])
        if project is None:
            continue
        parsed += 1
        ix = parse_project(project, progress)
        layouts = load_layouts(project, ix, progress)
        view = ProjectView(ContentInfo(r["sha256"], r["name"]), project, ix, layouts=layouts, modules=modules)
        found: dict[str, list[tuple[str, str, int | None]]] = defaultdict(list)  # stratum -> (key, dia, module)
        for dia_id in view.layouts:
            g = view.graph(dia_id)
            if g is None or g.trivial():
                continue
            part = view.partition(dia_id)
            kind = ix.diagrams[dia_id].diagram_type or "Diagram"
            if part is None:
                stratum = "small" if len(g.nodes) <= SMALL else "medium"
                found[stratum].append((kind, dia_id, None))
                kinds[stratum][kind] += 1
            else:
                for m in part.modules:
                    found["modules"].append((kind, dia_id, m.num))
                    kinds["modules"][kind] += 1
        for stratum, items in found.items():  # drawn now, while the project is parsed: a few per stratum
            items.sort(key=lambda t: hashlib.sha256(f"{r['sha256']}:{t[1]}:{t[2]}".encode()).hexdigest())
            for kind, dia_id, num in items[:PER_STRATUM * 2]:
                g = view.graph(dia_id)
                title = f"{kind}: {ix.qualified_name(dia_id)}"
                drawn: dict[int, str] = {}
                if num is None:
                    png = sketch.render_png(ix, g, title, pixels, style=style, drawn=drawn)
                    ends = set(drawn)
                else:
                    part = view.partition(dia_id)
                    png = sketch.module_png(ix, part, num, title, pixels, style, drawn)
                    m = part.modules[num - 1]
                    ends = set(m.shapes) | set(m.boundary)
                if png is None or not drawn:
                    continue
                pool[stratum].append(Sketch(f"{r['sha256'][:12]}:{dia_id}" + (f":M{num}" if num else ""), r["name"],
                                            ix.qualified_name(dia_id) + (f" (module M{num})" if num else ""), kind,
                                            stratum, png, _truth(g, drawn, ends)))
    chosen = []
    for stratum in strata(modules[0]):
        by_kind: dict[str, list[Sketch]] = defaultdict(list)
        for s in pool[stratum]:
            by_kind[s.kind].append(s)
        queues = [by_kind[k] for k, _ in kinds[stratum].most_common() if by_kind[k]]
        picked: list[Sketch] = []
        while queues and len(picked) < PER_STRATUM:  # round robin, the commonest kinds first
            for q in list(queues):
                if len(picked) < PER_STRATUM:
                    picked.append(q.pop(0))
                if not q:
                    queues.remove(q)
        chosen += picked
    return chosen


def _tokens(text: str) -> list[str]:
    cut = text.endswith("…")
    tokens = ec.norm(text.rstrip("…")).split()
    return tokens[:-1] if cut and tokens else tokens  # the last word of a cut name may be cut too


def score(truth: dict[str, Any], answer: dict[str, Any] | None) -> dict[str, Any]:
    """Shapes listed, words of their names read, connections found (either way round), and the
    directed ones found the right way round."""
    given: dict[int, str] = {}
    for s in (answer or {}).get("shapes") or []:
        try:
            given.setdefault(int(s.get("number")), str(s.get("name") or ""))
        except (AttributeError, TypeError, ValueError):
            continue
    pairs = []
    for c in (answer or {}).get("connections") or []:
        try:
            pairs.append((int(c.get("from")), int(c.get("to"))))
        except (AttributeError, TypeError, ValueError):
            continue
    shapes = {int(n): t for n, t in truth["shapes"].items()}
    words = read = 0
    for n, text in shapes.items():
        expected = _tokens(text)
        got = _tokens(given.get(n, ""))
        words += len(expected)
        read += sum(b.size for b in SequenceMatcher(None, expected, got, autojunk=False).get_matching_blocks())
    found = directed = right = 0
    for a, b, is_directed in truth["links"]:
        hit = next((p for p in pairs if p in ((a, b), (b, a))), None)
        if hit is None:
            continue
        pairs.remove(hit)
        found += 1
        if is_directed:
            directed += 1
            right += hit == (a, b)
    return {"shapes": len(shapes), "listed": sum(1 for n in shapes if n in given), "words": words, "read": read,
            "links": len(truth["links"]), "found": found, "directed": directed, "right": right,
            "unreadable": answer is None}


def ask(llm: EnrichmentSession, sketches: list[Sketch], image_first: bool, concurrency: int = 1,
        progress: Progress = QUIET) -> list[dict[str, Any]]:
    def one(s: Sketch) -> dict[str, Any]:
        res = llm.ask(TEMPLATE, {}, image=s.png, mime="image/png", project=f"validation:{s.project}",
                      inputs=(s.key,), image_first=image_first)
        reply = res[0] if res else None
        answer = ec.parse(reply)
        return {"key": s.key, "project": s.project, "diagram": s.diagram, "kind": s.kind, "stratum": s.stratum,
                "truth": s.truth, "reply": reply, "answer": answer, "asked": res is not None, **score(s.truth, answer)}

    with progress.phase("validation: the tree's sketches", len(sketches), "sketch") as ph, \
            ThreadPoolExecutor(max(1, concurrency)) as pool:
        futures = [pool.submit(one, s) for s in sketches]
        for done in as_completed(futures):
            done.result()
            ph.advance()
    return [f.result() for f in futures]


def _rates(rs: list[dict[str, Any]]) -> dict[str, Any]:
    def share(a: str, b: str) -> float | None:
        total = sum(r[b] for r in rs)
        return sum(r[a] for r in rs) / total if total else None

    return {"sketches": len(rs), "listed": share("listed", "shapes"), "names": share("read", "words"),
            "found": share("found", "links"), "directions": share("right", "directed")}


def summarize(results: list[dict[str, Any]], large: int) -> dict[str, Any]:
    labels = strata(large)
    by = {k: _rates([r for r in results if r["stratum"] == k])
          for k in labels if any(r["stratum"] == k for r in results)}
    warnings = []
    for k, rates in by.items():
        for measure, what, consequence in (
                ("names", "names read", "their descriptions rely on the legend's text for names"),
                ("found", "connections found", "their descriptions may misplace connections"),
                ("directions", "directions right", ("their descriptions get directions as text, but may "
                                                    "contradict them"))):
            if rates[measure] is not None and rates[measure] < PASS:
                warnings.append(f"{labels[k]}: {rates[measure]:.0%} of {what}; {consequence}")
    unreadable = sum(1 for r in results if r["asked"] and r["answer"] is None)
    unasked = sum(1 for r in results if not r["asked"])
    if (unreadable + unasked) * 2 > len(results):
        warnings.insert(0, f"{unreadable + unasked} of {len(results)} sketches got no readable reply: the validation "
                           "says little")
    return {"overall": _rates(results), "strata": by, "warnings": warnings, "unreadable": unreadable,
            "unasked": unasked}


def one_line(summary: dict[str, Any]) -> str:
    o = summary["overall"]
    if not o["sketches"]:
        return "no diagrams in the tree to sample"
    parts = [f"{o[k]:.0%} {what}" for k, what in (("names", "of names read"), ("found", "of connections found"),
                                                  ("directions", "of directions right")) if o[k] is not None]
    return f"on {o['sketches']} of the tree's sketches, " + ", ".join(parts)


def render(model: str, summary: dict[str, Any], results: list[dict[str, Any]], large: int) -> str:
    def pct(x: float | None) -> str:
        return "-" if x is None else f"{x:.0%}"

    labels = strata(large)
    lines = [f"# Validation on the tree's sketches: {model}", "",
             ("What the model reads on the tree's own diagrams, drawn at the sizes runs use, from the image "
              "alone. Descriptions also get every name and connection as text, so they should do better."), "",
             "| Sample | Sketches | Shapes listed | Names read | Connections found | Directions right |",
             "|---|---|---|---|---|---|"]
    for k, r in [*summary["strata"].items(), ("overall", summary["overall"])]:
        lines.append(f"| {labels.get(k, 'all')} | {r['sketches']} | {pct(r['listed'])} | {pct(r['names'])} | "
                     f"{pct(r['found'])} | {pct(r['directions'])} |")
    if summary["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in summary["warnings"]]
    lines += ["", "## Sketches", "", "| Sketch | Project | Type | Names read | Connections found | Directions right |",
              "|---|---|---|---|---|---|"]
    for r in results:
        rates = _rates([r])
        lines.append(f"| {r['diagram']} | {r['project']} | {r['kind']} | {pct(rates['names'])} | "
                     f"{pct(rates['found'])} | {pct(rates['directions'])} |")
    return "\n".join(lines) + "\n"


def validate(state: State, llm: EnrichmentSession, settings: TreeSettings, dest: Path, concurrency: int = 1,
             progress: Progress = QUIET) -> dict[str, Any] | None:
    """Sample, draw, ask and score; write `validation.md`, `validation.json` and the sketches beside
    the calibration's report, and record the summary with the model's calibration (with no
    sketches when the tree has no diagrams to sample, so that runs don't look again)."""
    sketches = sample(state, settings, progress)
    results = ask(llm, sketches, settings.image_first is not False, concurrency, progress) if sketches else []
    large = settings.modules[0]
    summary = summarize(results, large)
    (dest / "validation").mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(sketches, 1):
        (dest / "validation" / f"{i:02d}-{s.stratum}.png").write_bytes(s.png)
    (dest / "validation.json").write_text(json.dumps({"summary": summary, "sketches": results}, indent=1,
                                                     ensure_ascii=False), encoding="utf-8")
    (dest / "validation.md").write_text(render(llm.cfg.vision_model or "", summary, results, large), encoding="utf-8")
    from .calibrate import SUITE_VERSION

    state.save_validation(llm.cfg.base_url or "", llm.cfg.vision_model or "", SUITE_VERSION, summary)
    return summary

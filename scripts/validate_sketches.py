#!/usr/bin/env python3
"""Compare what a vision model reads on the same diagrams drawn by two versions (plan SK-04).

    # choose the sample, with this version: by stratum, and targeted at the faults plan SK fixed
    uv run python scripts/validate_sketches.py choose out/va/v013 -o out/sk/keys.json
    # draw and ask, with any version from 0.13.0 on (PYTHONPATH=<worktree>/src for an old one)
    uv run python scripts/validate_sketches.py ask out/va/v013 out/sk/keys.json -o out/sk/new-gemma.jsonl \\
        --env .env --model google/gemma-4-31B-it --cache-dir out/vc/after/.cache
    # score every run alike, with this version, side by side
    uv run python scripts/validate_sketches.py score out/sk/old-gemma.jsonl out/sk/new-gemma.jsonl

`ask` uses only what 0.13.0 also has (its validation's drawing, truth and prompt), so that the
old version draws its own sketches; `score` scores every run with this version's measures,
connections invented among them. The diagrams are the same by key; the shapes' numbers, and a
large diagram's modules, may differ between versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cameo_ingest
from cameo_ingest import eyechart as ec
from cameo_ingest import sketch, validate
from cameo_ingest.cli import load_env
from cameo_ingest.config import IMAGE_PIXELS, MODULES, SKETCH, TreeSettings
from cameo_ingest.llm import EnrichmentSession, LLMConfig, connect
from cameo_ingest.pipeline import load_layouts, parse_project
from cameo_ingest.provenance import ContentInfo
from cameo_ingest.sketch import SketchStyle
from cameo_ingest.state import State
from cameo_ingest.view import ProjectView

FAULTS = ("tree", "label", "association-class", "covered")  # what plan SK changed


def faults(view, g, layout) -> set[str]:
    """The faults plan SK fixed that a diagram has."""
    classes = {v.cls for v in layout.views}
    found = {"tree"} if g.trees else set()
    if classes & {"AssociationTextBox", "MessageSignature"}:
        found.add("label")
    if "LinkAttribute" in classes:
        found.add("association-class")
    if _covered(view, g):
        found.add("covered")
    return found


def _covered(view, g) -> bool:
    """A shape inside a larger one of the same depth listed after it (drawn under it before SK)."""
    nodes = [n for n in g.nodes if n.view.rect]
    pos = {id(n.view): i for i, n in enumerate(nodes)}

    def inside(a, b):
        return b[0] <= a[0] and b[1] <= a[1] and a[0] + a[2] <= b[0] + b[2] and a[1] + a[3] <= b[1] + b[3]

    return any(m is not n and m.depth == n.depth and pos[id(m.view)] > pos[id(n.view)]
               and inside(n.view.rect, m.view.rect) for n in nodes for m in nodes)


def choose(tree: Path, per_stratum: int, targeted: int, max_projects: int, sizes: TreeSettings,
           wanted: tuple[str, ...] = FAULTS) -> list[dict]:
    state = State(tree)
    try:
        picked = validate.sample(state, sizes, per_stratum=per_stratum, max_projects=max_projects)
        keys = [{"content": s.content, "dia": s.dia_id, "module": s.module, "stratum": s.stratum} for s in picked]
        seen = {(k["content"], k["dia"]) for k in keys}
        found: dict[str, list[dict]] = defaultdict(list)  # by project, whole diagrams with a fault
        rows = [r for r in state.catalog() if r["status"] != "removed"
                and state.content(r["sha256"])["size"] <= validate.MAX_BYTES]
        rows.sort(key=lambda r: hashlib.sha256(r["sha256"].encode()).hexdigest())
        for r in rows[:max_projects * 2]:
            project = validate._project(state, r["sha256"])
            if project is None:
                continue
            ix = parse_project(project)
            view = ProjectView(ContentInfo(r["sha256"], r["name"]), project, ix, layouts=load_layouts(project, ix),
                               modules=sizes.modules)
            for dia_id, layout in view.layouts.items():
                g = view.graph(dia_id)
                if g is None or g.trivial() or view.partition(dia_id) is not None or (r["sha256"], dia_id) in seen:
                    continue
                if faults(view, g, layout) & set(wanted):
                    found[r["sha256"]].append({"content": r["sha256"], "dia": dia_id, "module": None,
                                               "stratum": "targeted"})
        queues = [sorted(q, key=lambda k: hashlib.sha256(k["dia"].encode()).hexdigest()) for q in found.values()]
        while queues and sum(k["stratum"] == "targeted" for k in keys) < targeted:  # projects take turns
            for q in list(queues):
                if sum(k["stratum"] == "targeted" for k in keys) < targeted:
                    keys.append(q.pop(0))
                if not q:
                    queues.remove(q)
        return keys
    finally:
        state.close()


def ask(tree: Path, keys: list[dict], llm: EnrichmentSession, sizes: TreeSettings, image_first: bool,
        concurrency: int, guides: bool = True) -> list[dict]:
    state = State(tree)
    pixels, style = sizes.image_pixels or IMAGE_PIXELS, SketchStyle(*sizes.sketch)
    drawn_all = []
    try:
        by_content: dict[str, list[dict]] = defaultdict(list)
        for k in keys:
            by_content[k["content"]].append(k)
        for sha, ks in by_content.items():
            project = validate._project(state, sha)
            name = state.content(sha)["name"]
            ix = parse_project(project)
            view = ProjectView(ContentInfo(sha, name), project, ix, layouts=load_layouts(project, ix),
                               modules=sizes.modules)
            for k in ks:
                g = view.graph(k["dia"])
                kind = ix.diagrams[k["dia"]].diagram_type or "Diagram"
                title = f"{kind}: {ix.qualified_name(k['dia'])}"
                drawn: dict[int, str] = {}
                part = view.partition(k["dia"])
                if k["module"] is None:
                    png = sketch.render_png(g, title, pixels, style=style, drawn=drawn)
                    ends, focus = set(drawn), None
                elif part is not None and k["module"] <= len(part.modules):
                    png = sketch.module_png(part, k["module"], title, pixels, style, drawn)
                    m = part.modules[k["module"] - 1]
                    ends, focus = set(m.shapes) | set(m.boundary), set(m.shapes)
                else:
                    continue  # this version divides the diagram otherwise
                values = {}  # how to read it, from versions that say (plan SK)
                if guides and hasattr(sketch, "conventions"):
                    values = {"GUIDE": validate.guide(validate.TEMPLATE, sketch.conventions(g, focus))}
                elif "{{GUIDE}}" in validate.TEMPLATE.text:
                    values = {"GUIDE": ""}
                if png:
                    drawn_all.append((k, name, kind, ix.qualified_name(k["dia"]), png, validate._truth(g, drawn, ends),
                                      values))
    finally:
        state.close()

    def one(item):
        k, name, kind, diagram, png, truth, values = item
        res = llm.ask(validate.TEMPLATE, values, image=png, mime="image/png", project=f"validation:{name}",
                      inputs=(f"{k['content'][:12]}:{k['dia']}:{k['module']}",), image_first=image_first)
        return {**k, "project": name, "kind": kind, "diagram": diagram, "truth": truth, "guide": values.get("GUIDE"),
                "reply": res[0] if res else None, "version": cameo_ingest.__version__,
                "png_sha256": hashlib.sha256(png).hexdigest()}

    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        return list(pool.map(one, drawn_all))


def score(paths: list[Path]) -> str:
    runs = {}
    for p in paths:
        rows = [json.loads(line) for line in p.open(encoding="utf-8")]
        results = [{**r, **validate.score(r["truth"], ec.parse(r["reply"]))} for r in rows]
        strata = {s: validate._rates([r for r in results if r["stratum"] == s])
                  for s in ("small", "medium", "modules", "targeted") if any(r["stratum"] == s for r in results)}
        runs[p.stem] = {**strata, "all": validate._rates(results)}

    def pct(x):
        return "-" if x is None else f"{x:.0%}"

    lines = ["| Run | Sample | Sketches | Names read | Connections found | Directions right | Invented |",
             "|---|---|---|---|---|---|---|"]
    for name, strata in runs.items():
        for s, r in strata.items():
            lines.append(f"| {name} | {s} | {r['sketches']} | {pct(r['names'])} | {pct(r['found'])} | "
                         f"{pct(r['directions'])} | {pct(r['invented'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="step", required=True)
    sizes = argparse.ArgumentParser(add_help=False)
    sizes.add_argument("--pixels", type=int, default=IMAGE_PIXELS)
    sizes.add_argument("--font", type=int, default=SKETCH[0])
    sizes.add_argument("--arrow", type=float, default=SKETCH[1])
    sizes.add_argument("--line", type=int, default=SKETCH[2])
    sizes.add_argument("--modules", default=":".join(map(str, MODULES)))
    c = sub.add_parser("choose", parents=[sizes])
    c.add_argument("tree", type=Path)
    c.add_argument("-o", "--out", type=Path, required=True)
    c.add_argument("--per-stratum", type=int, default=12)
    c.add_argument("--targeted", type=int, default=12)
    c.add_argument("--max-projects", type=int, default=8)
    c.add_argument("--faults", default=",".join(FAULTS), help="the faults the targeted sketches have (any of them)")
    a = sub.add_parser("ask", parents=[sizes])
    a.add_argument("tree", type=Path)
    a.add_argument("keys", type=Path)
    a.add_argument("-o", "--out", type=Path, required=True)
    a.add_argument("--env", type=Path)
    a.add_argument("--model", required=True)
    a.add_argument("--cache-dir", type=Path, required=True)
    a.add_argument("--concurrency", type=int, default=4)
    a.add_argument("--image-last", action="store_true")
    a.add_argument("--no-guides", action="store_true", help="leave out how to read the sketch (plan SK)")
    s = sub.add_parser("score")
    s.add_argument("runs", type=Path, nargs="+")
    args = ap.parse_args()
    if args.step == "score":
        print(score(args.runs))
        return
    settings = TreeSettings(image_pixels=args.pixels, diagram_modules=args.modules, sketch_font_px=args.font,
                            sketch_arrow_px=args.arrow, sketch_line_px=args.line)
    if args.step == "choose":
        keys = choose(args.tree, args.per_stratum, args.targeted, args.max_projects, settings,
                      tuple(args.faults.split(",")))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(keys, indent=1), encoding="utf-8")
        print(f"{len(keys)} sketches: " + ", ".join(f"{n} {s}" for s, n in sorted(
            {k['stratum']: sum(x['stratum'] == k['stratum'] for x in keys) for k in keys}.items())))
        return
    if args.env:
        load_env(args.env)
    cfg = LLMConfig.from_env(None, args.model)
    cfg.text_model = None
    llm = EnrichmentSession(cfg, args.cache_dir, connect(cfg, None))
    rows = ask(args.tree, json.loads(args.keys.read_text()), llm, settings, not args.image_last, args.concurrency,
               not args.no_guides)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} sketches asked with {cameo_ingest.__version__}; {llm.calls} requests sent")


if __name__ == "__main__":
    main()

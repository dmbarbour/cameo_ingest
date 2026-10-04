"""Measuring the quality of LLM enrichment (plan docs/archive/plans/llm-quality-2026-09-30.md).

`sample` draws a spot-check set from an output tree: its generated chunks, joined with the
request log in llm.sqlite, so that each item shows exactly what the model was asked and what
it answered. A set is written to OUT/quality/<set>/ and never changed afterwards:

    set.json            how the set was drawn
    items.jsonl         the items: request, image, response, reference material
    templates.jsonl     the prompt templates the items used, with stand-ins for their slots
    index.html          one self-contained page to read and rate everything
    rate-items.csv      blank rating sheets (copy to ratings-items-<rater>.csv and fill in)
    rate-templates.csv  (copy to ratings-templates-<rater>.csv)
"""

from __future__ import annotations

import base64
import csv
import datetime as _dt
import html
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .llm import STORE_FILE, ResponseStore
from .prompts import TEMPLATES
from .provenance import TOOL, Derivation, generated_by, utc_now

ITEM_RUBRIC = [
    ("faithful", "yes / partly / no: every element, relationship and claim is supported by the input"),
    ("errors", "the unsupported or wrong statements (invented elements or groupings, wrong directions)"),
    ("omissions", "important content left out (main elements, flows, requirements)"),
    ("useful", "1 to 5: would this text help someone find the item with a natural question?"),
    ("format", "ok / not ok: plain prose, within the length limit, no markup"),
    ("fault", "model / input / both / none: where a problem comes from"),
    ("notes", "free text"),
]
TEMPLATE_RUBRIC = [
    ("clear", "1 to 5: is the task unambiguous? Would two careful people produce comparable answers?"),
    ("grounded", ("yes / partly / no: does it confine the answer to the input, and say what to do when the "
                 "input is not enough?")),
    ("context", ("complete / gaps: does the input carry what the task needs (notation, direction conventions, "
                "what the lists include and leave out, whether anything was cut)?")),
    ("accurate", "yes / no: are the template's own statements about its input true?"),
    ("output_spec", "ok / not ok: are the length, format, audience and required content stated?"),
    ("risks", "the errors the template invites (speculation, invented structure, markup, over-long answers)"),
    ("suggestions", "concrete changes"),
    ("notes", "free text"),
]


def _strip_front_matter(text: str) -> str:
    return text.split("\n---\n", 1)[1] if text.startswith("---\n") else text


def _reference(out: Path, rel: str, model: str, response: str) -> str:
    """The page the item belongs to, without the response itself, so a rater checks the
    answer against the source rather than against itself."""
    path = out / rel.partition("#")[0]
    if not path.is_file():
        return ""
    text = _strip_front_matter(path.read_text(encoding="utf-8"))
    # Under whatever label it appears (emit.annotation_md): "Summary", "Summary of parts 1 to 3", ...
    answer = re.compile(r"\*\*[^*\n]+\*\* " +
                        re.escape(f"_({generated_by(Derivation('llm', model=model))})_:\n\n{response}\n"))
    return answer.sub("", text)


def collect_items(out: Path, store_path: Path) -> tuple[list[dict[str, Any]], int]:
    """Every generated chunk of the tree that the request log can explain, and how many it
    could not (answered before the log existed: run again to log them)."""
    store = ResponseStore(store_path, readonly=True)
    items, unexplained = [], 0
    answers: dict[str, list[dict[str, Any]]] = {}  # an answer's pieces, by its annotation id (AR-012R2)
    for line in (out / "chunks.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        if c["metadata"]["kind"].startswith("generated:"):
            answers.setdefault(c["metadata"].get("annotation") or c["id"], []).append(c)
    for answer_id, pieces in answers.items():
        c = pieces[0]
        meta = c["metadata"]
        d = meta["provenance"]["derivation"]
        req = store.request(d["model"], d["prompt_sha256"])
        if req is None:
            unexplained += 1
            continue
        # A long answer is split at lines into pieces, each under its heading: joined again.
        response = "\n".join(p["text"].split("\n\n", 1)[1]
                              for p in sorted(pieces, key=lambda p: p["metadata"].get("piece", 1)))
        sha = meta["content"].removeprefix("sha256:")
        items.append({
            "id": answer_id,
            "kind": meta["kind"].removeprefix("generated:"),
            "template": req["template"],
            "model": d["model"],
            "request": d["prompt_sha256"],
            "project": meta["project"],
            "content": meta["content"],
            "element": meta.get("qualified_name") or c["title"],
            "locator": req["item"],
            "prompt": req["prompt"],
            "notes": json.loads(req["notes"]),
            "image": f"by-sha256/{sha}/{req['image_path']}" if req["image_path"] else None,
            "reference_file": meta["file"],
            "reference": _reference(out, meta["file"], d["model"], response),
            "response": response,
        })
    return items, unexplained


def _draw(items: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """A stratified sample: kinds take turns, and within a kind, items whose input was cut
    to fit the prompt make up to half the share."""
    rng = random.Random(seed)
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in sorted(items, key=lambda i: i["id"]):
        by_kind[it["kind"]].append(it)
    queues = {}
    for kind, group in sorted(by_kind.items()):
        rng.shuffle(group)
        cut = [i for i in group if "truncated" in i["notes"]]
        whole = [i for i in group if "truncated" not in i["notes"]]
        mixed = []  # alternate, so that at most about half are truncated while both kinds last
        while cut or whole:
            for q in (whole, cut):
                if q:
                    mixed.append(q.pop(0))
        queues[kind] = mixed
    chosen: list[dict[str, Any]] = []
    while len(chosen) < n and any(queues.values()):
        for kind in sorted(queues):
            if queues[kind] and len(chosen) < n:
                chosen.append(queues[kind].pop(0))
    return chosen


def sample(out: Path, cache_dir: Path, n: int = 30, seed: int = 1, kinds: list[str] | None = None) -> Path:
    """Draw a spot-check set from the tree `out`, whose LLM store is in `cache_dir`."""
    if not (cache_dir / STORE_FILE).is_file():
        raise FileNotFoundError(f"no LLM store at {cache_dir / STORE_FILE}: nothing was generated")
    items, unexplained = collect_items(out, cache_dir / STORE_FILE)
    if kinds:
        items = [i for i in items if i["kind"] in kinds]
    chosen = _draw(items, n, seed)
    if not chosen:
        raise ValueError("no generated item to sample" + (f" ({unexplained} predate the request log; run again)"
                                                          if unexplained else ""))
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M%S")
    base = out / "quality" / f"{stamp}-seed{seed}"
    set_dir, k = base, 1
    while set_dir.exists():  # two sets drawn within the same second
        k += 1
        set_dir = base.with_name(f"{base.name}-{k}")
    set_dir.mkdir(parents=True)
    used = sorted({i["template"] for i in chosen})
    templates = [_template_record(k) for k in used]
    meta = {"set": set_dir.name, "created": utc_now(), "tool": TOOL, "seed": seed, "n": n, "kinds": kinds,
            "items": len(chosen), "available": len(items), "unexplained": unexplained, "templates": used}
    (set_dir / "set.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    with (set_dir / "items.jsonl").open("w", encoding="utf-8") as f:
        for it in chosen:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with (set_dir / "templates.jsonl").open("w", encoding="utf-8") as f:
        for t in templates:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with (set_dir / "rate-items.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "kind", "element", *(k for k, _ in ITEM_RUBRIC)])
        w.writerows([i["id"], i["kind"], i["element"]] + [""] * len(ITEM_RUBRIC) for i in chosen)
    with (set_dir / "rate-templates.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["template", *(k for k, _ in TEMPLATE_RUBRIC)])
        w.writerows([t["key"]] + [""] * len(TEMPLATE_RUBRIC) for t in templates)
    (set_dir / "index.html").write_text(_page(out, meta, templates, chosen), encoding="utf-8")
    return set_dir


def _template_record(key: str) -> dict[str, Any]:
    t = TEMPLATES.get(key)
    if t is None:  # a version no longer in the code: its requests still show the text used
        return {"key": key, "stand_in": None, "purpose": None, "slots": []}
    return {"key": key, "id": t.id, "version": t.version, "purpose": t.purpose, "text": t.text,
            "stand_in": t.stand_in(),
            "slots": [{"name": s.name, "kind": s.kind, "description": s.description} for s in t.slots]}


# -- the spot-check page ---------------------------------------------------------------
_CSS = """
:root { --bg: #fff; --fg: #1d1d1f; --muted: #6b6b70; --line: #d9d9de; --box: #f5f5f7; --slot: #fff1c2; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161618; --fg: #ececf0; --muted: #a0a0a8; --line: #3a3a40; --box: #222226; --slot: #4a3d10; }
}
body { background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; margin: 0 auto;
       max-width: 1100px; padding: 16px; }
h1, h2, h3 { line-height: 1.25; } h2 { margin-top: 2.5em; border-bottom: 1px solid var(--line); }
section { border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; margin: 16px 0; }
pre { background: var(--box); padding: 10px; border-radius: 6px; white-space: pre-wrap; word-break: break-word;
      font-size: 13px; }
.slot { background: var(--slot); border-radius: 3px; }
.meta { color: var(--muted); font-size: 13px; } .response { font-size: 15px; }
img { max-width: 100%; border: 1px solid var(--line); background: #fff; }
table { border-collapse: collapse; } td, th { border: 1px solid var(--line); padding: 4px 8px; vertical-align: top; }
code { font-size: 13px; }
"""


def _pre(text: str, slots: bool = False) -> str:
    body = html.escape(text)
    if slots:  # highlight the stand-ins
        body = body.replace("⟦", '<span class="slot">⟦').replace("⟧", "⟧</span>")
    return f"<pre>{body}</pre>"


def _rubric_table(rubric: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><td><code>{k}</code></td><td>{html.escape(v)}</td></tr>" for k, v in rubric)
    return f"<table>{rows}</table>"


def _page(out: Path, meta: dict[str, Any], templates: list[dict[str, Any]], items: list[dict[str, Any]]) -> str:
    e = html.escape
    parts = [(f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>Spot check {e(meta['set'])}</title><style>{_CSS}</style></head><body>"),
             f"<h1>Spot check {e(meta['set'])}</h1>",
             (f"<p class='meta'>{meta['items']} items drawn from {meta['available']} (seed {meta['seed']}), "
             f"{len(templates)} templates. Made by {e(meta['tool'])} on {e(meta['created'])}.</p>"),
             ("<p>Rate the <a href='#templates'>templates</a> and the <a href='#items'>items</a>: copy "
             "<code>rate-templates.csv</code> and <code>rate-items.csv</code> from this directory to "
             "<code>ratings-templates-&lt;you&gt;.csv</code> and <code>ratings-items-&lt;you&gt;.csv</code>, "
             "and fill in one row per template or item. Each item shows what the model was asked (the "
             "prompt and image), its answer, and the page it belongs to without that answer.</p>"),
             "<h2>Rubrics</h2><h3>Templates</h3>", _rubric_table(TEMPLATE_RUBRIC),
             "<h3>Items</h3>", _rubric_table(ITEM_RUBRIC), "<h2 id='templates'>Templates</h2>"]
    for t in templates:
        parts.append(f"<section><h3><code>{e(t['key'])}</code></h3>")
        if t["stand_in"] is None:
            parts.append("<p>This version is no longer in the code; see the items' prompts.</p></section>")
            continue
        parts.append(f"<p>{e(t['purpose'])}</p><p class='meta'>The request, with a stand-in for each slot:</p>"
                     + _pre(t["stand_in"], slots=True) + "</section>")
    parts.append("<h2 id='items'>Items</h2>")
    for n, it in enumerate(items, 1):
        notes = "; ".join(f"{k}: {json.dumps(v)}" for k, v in it["notes"].items())
        parts.append(
            f"<section id='{e(it['id'])}'><h3>{n}. {e(it['kind'].replace('_', ' '))}: {e(it['element'])}</h3>"
            f"<p class='meta'>item <code>{e(it['id'])}</code> · template <code>{e(it['template'])}</code> · model "
            f"<code>{e(it['model'])}</code> · project {e(it['project'])} · <code>{e(it['locator'])}</code>"
            + (f" · <b>input cut:</b> {e(notes)}" if notes else "") + "</p>")
        if it["image"]:
            img = out / it["image"]
            if img.is_file():
                mime = "image/png" if img.suffix == ".png" else f"image/{img.suffix.lstrip('.')}"
                data = base64.b64encode(img.read_bytes()).decode()
                parts.append(f"<p><img alt='the image sent with the request' src='data:{mime};base64,{data}'></p>")
        long = len(it["prompt"]) > 4000
        parts.append(f"<details{'' if long else ' open'}><summary>Request text "
                     f"({len(it['prompt']):,} characters)</summary>{_pre(it['prompt'])}</details>")
        parts.append(f"<h4>Response</h4><div class='response'>{_pre(it['response'])}</div>")
        if it["reference"]:
            parts.append(f"<details><summary>Reference: <code>{e(it['reference_file'])}</code> without the "
                         f"response</summary>{_pre(it['reference'])}</details>")
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)

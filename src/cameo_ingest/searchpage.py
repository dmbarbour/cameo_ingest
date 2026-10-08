"""The catalog as one self-contained web page, searched in a browser opened from disk (plan KX-04).

The page holds its code (`assets/search.js`, `assets/search.css`, `assets/search.html`) and its
data: one block per project, base64 of gzipped JSON, which the page unpacks, indexes and
searches (BM25, as the retrieval evaluation measured), showing what it is doing as it loads.
It loads nothing from the network.

Each project's block holds `project` (label, file name, token, sources, counts, and its facts,
`lineage.facts`: `sv` save time, `ex` Cameo version, `fm` its family's newest token, `rk` its rank
there, `nv` the family's versions, `kn` kin `[token, how]`, `rl` related tokens) and `items`,
objects with short keys to keep the page small:

    k key   t type   kd kind   id requirement id   db database number   n name   w where
    x text (requirement text, documentation, summary)   c the item's chunks, as the RAG reads them
    r relations [kind, direction, phrase, other key, other label]   d diagrams [key, label]
    l listed in [key, label] (a member, which borrows its owner's chunks: not repeated here)
    m model (generated text)   of [key, label] (what a summary is of)   pt its module or parts
    sk the ids of a diagram's sketch blocks (`--sketches`), the whole diagram first
    tg a diagram's number tags {"n": element key}: the "[n]" in its text and its modules' (TR-005)
    al its copies in other models (plan SH): [the other's token, 16 hex digits; its key; the basis,
       "e" element, "i" requirement Id, "n" name; what differs, "" for nothing]

Sketches, when asked for (plan KX-05), follow in blocks of their own, decoded only when their
diagram is opened: `webp`, the tree's PNG sketches (and a large diagram's modules) re-encoded
losslessly; `svg`, the SVG sketches, gzipped.

Relationship records stay in the workbook: the page shows them on their items.

The families' subjects (`subjects.json`, ADR-0031), when the tree has them, follow in one block,
`data-subjects`, gzipped JSON: a list of families, each

    n its newest project's label (rivals often share a file name)   p its projects (page ids), newest
    first   dv the default view's id
    k {diagram key: the page id of the newest project holding it}   vs {diagram key: versions}, if over 1
    v views: [{id, t title, kd kind, s subjects [{l label, h what it holds, d diagram keys}], u unsorted keys}]

The topics across models (plan SB CP4), when the tree has them, follow in `data-topics`, gzipped
JSON: `{dv the default view's id, v views: [{id, t title, kd kind, s topics [{l label, h what it
holds, m members [[family, subject]]}], u unsorted members}]}`; a member is a family of
`data-subjects` (its index) and a subject of that family's default view (its index).
"""

from __future__ import annotations

import base64
import gzip
import html
import io
import json
from collections.abc import Iterable
from importlib import resources
from pathlib import Path
from typing import Any

from .catalog import ProjectCatalog
from .discovery import split_ref
from .shared import BASES
from .text import plural

TITLE = "Model search"


def _asset(name: str) -> str:
    return (resources.files("cameo_ingest") / "assets" / name).read_text(encoding="utf-8")


SKETCHES = ("none", "webp", "svg")


def _webp(path: Path) -> str | None:
    from PIL import Image

    try:
        with Image.open(path) as im:
            buf = io.BytesIO()
            im.save(buf, "WEBP", lossless=True, method=4)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except OSError:
        return None


def sketch_blocks(p: ProjectCatalog, pid: int, record: dict[str, Any], sketches: str) -> list[tuple[str, str, str]]:
    """A diagram's sketch blocks, as (id, format, base64); the whole diagram first."""
    if sketches == "none" or p.dir is None:
        return []
    out = []
    if sketches == "svg" and record.get("svg") and (p.dir / record["svg"]).is_file():
        svg = (p.dir / record["svg"]).read_bytes()
        out.append(("svg", base64.b64encode(gzip.compress(svg, 9, mtime=0)).decode("ascii")))
    elif sketches == "webp":
        for rel in [record.get("sketch"), *record.get("modules", [])]:
            if rel and (p.dir / rel).is_file() and (b64 := _webp(p.dir / rel)):
                out.append(("webp", b64))
    return [(f"s{pid}-{record['key']}-{i}", fmt, b64) for i, (fmt, b64) in enumerate(out)]


BASIS = dict(zip(BASES, "ein", strict=True))


def page_items(p: ProjectCatalog, sketch_ids: dict[str, list[str]] | None = None,
               links: dict[tuple[str, str], list[Any]] | None = None) -> list[dict[str, Any]]:
    """The project's records as the page's items, each with its chunks' text, and its copies in
    other models (`shared.find`)."""
    token = p.header.get("token") or ""
    out = []
    for r in p.records:
        t = r["type"]
        if t == "relationship":
            continue
        if t == "summary":
            it = {"k": r["key"], "t": t, "kd": r["label"], "n": f"{r['label']} of {r['of'][1]}", "x": r["text"],
                  "m": r.get("model"), "of": r["of"]}
            if "module" in r:
                it["pt"] = f"module M{r['module']}"
            if "parts" in r:
                it["pt"] = f"parts {r['parts'][0]}–{r['parts'][1]}"
            if "pt" in it:
                it["n"] += ", " + it["pt"]
        else:
            it = {"k": r["key"], "t": t, "kd": r.get("kind"), "id": r.get("id"), "db": r.get("db"), "n": r["name"],
                  "w": r.get("where"), "x": r.get("text"),
                  "r": [rel[1:] for rel in r.get("relations", [])], "l": r.get("listed_in"),
                  "d": [d for d in r.get("diagrams", []) if d[0] != r["key"]]}  # not itself (catalogs before 0.8.2)
            if not r.get("listed_in"):
                it["c"] = "\n\n".join(p.chunks[c] for c in r.get("chunks", []) if c in p.chunks)
            if sketch_ids and r["key"] in sketch_ids:
                it["sk"] = sketch_ids[r["key"]]
            if r.get("tags"):
                it["tg"] = r["tags"]
            if links and (found := links.get((token, r["key"]))):
                it["al"] = [[lk.other.token.removeprefix("sha256:")[:16], lk.other.key, BASIS[lk.basis],
                             "; ".join(lk.differences)] for lk in found]
        out.append({k: v for k, v in it.items() if v not in (None, "", [])})
    return out


def page_subjects(families: list[dict[str, Any]], pids: dict[str, int], labels: dict[str, str]) -> list[dict[str, Any]]:
    """`subjects.json`'s families for the page, by label: tokens as page ids; families none of whose
    projects is in the page are left out."""
    out = []
    for f in families:
        tokens = [t for t in f["tokens"] if t in pids]
        if not tokens:
            continue
        k, vs = {}, {}
        for key, held in f["diagrams"].items():
            mine = [f["tokens"][i] for i in held if f["tokens"][i] in pids]
            if mine:
                k[key] = pids[mine[0]]
                if len(mine) > 1:
                    vs[key] = len(mine)
        views = []
        for v in f["views"]:
            view = {"id": v["id"], "t": v["title"], "kd": v["kind"],
                    "s": [{"l": s["label"], **({"h": s["holds"]} if s.get("holds") else {}),
                           "d": [d for d in s["diagrams"] if d in k]} for s in v["subjects"]]}
            if v.get("unsorted"):
                view["u"] = [d for d in v["unsorted"] if d in k]
            views.append(view)
        out.append({"n": labels.get(tokens[0], f["name"]), "p": [pids[t] for t in tokens], "dv": f["default"], "k": k,
                    "vs": vs, "v": views})
    return sorted(out, key=lambda f: (f["n"].lower(), f["p"]))


def page_topics(topics: dict[str, Any] | None, families: list[dict[str, Any]], page_fams: list[dict[str, Any]],
                pids: dict[str, int]) -> dict[str, Any] | None:
    """`subjects.json`'s topics for the page: members as (family, subject) indexes into `page_fams`,
    those of families not in the page left out; None when there are none."""
    if not topics or not topics.get("views"):
        return None
    fi_of = {f["p"][0]: fi for fi, f in enumerate(page_fams)}
    where: dict[str, int] = {}
    for f in families:
        first = next((pids[t] for t in f["tokens"] if t in pids), None)
        if first is not None and first in fi_of:
            where[f["tokens"][0]] = fi_of[first]

    def member(ref: str) -> list[int] | None:
        token, n = split_ref(ref)
        return [where[token], n] if token in where else None

    views = []
    for v in topics["views"]:
        ts = []
        for t in v["topics"]:
            ms = [m for m in map(member, t["subjects"]) if m]
            if ms:
                ts.append({"l": t["label"], **({"h": t["holds"]} if t.get("holds") else {}), "m": ms})
        view = {"id": v["id"], "t": v["title"], "kd": v["kind"], "s": ts}
        unsorted = [m for m in map(member, v.get("unsorted") or []) if m]
        if unsorted:
            view["u"] = unsorted
        if ts:
            views.append(view)
    if not views:
        return None
    dv = topics["default"] if any(v["id"] == topics["default"] for v in views) else views[0]["id"]
    return {"dv": dv, "v": views}


def write_search_page(path: Path, projects: Iterable[ProjectCatalog], version: str,
                      sketches: str = "none", subjects: dict[str, Any] | None = None,
                      facts: dict[str, dict[str, Any]] | None = None,
                      links: dict[tuple[str, str], list[Any]] | None = None) -> dict[str, int]:
    """Write the page; returns its counts (projects, items, bytes of data, sketches). `subjects`:
    the tree's `subjects.json`, if any."""
    blocks: list[tuple[str, int, str]] = []
    pictures: list[tuple[str, str, str]] = []
    pids: dict[str, int] = {}
    labels: dict[str, str] = {}
    n_items = 0
    for pid, p in enumerate(projects):
        if p.header.get("token"):
            pids[p.header["token"]] = pid
            labels[p.header["token"]] = p.label
        sketch_ids: dict[str, list[str]] = {}
        for r in p.records:
            if r["type"] == "diagram" and (found := sketch_blocks(p, pid, r, sketches)):
                sketch_ids[r["key"]] = [i for i, _, _ in found]
                pictures += found
        items = page_items(p, sketch_ids, links)
        n_items += len(items)
        fact = (facts or {}).get(p.header.get("token") or "", {})
        data = {"project": {"label": p.label, "name": p.header.get("name"), "token": p.header.get("token"),
                            "sources": p.sources, "counts": p.header.get("counts", {}),
                            **{k: fact[f] for k, f in (("sv", "saved"), ("ex", "exporter"), ("fm", "family"),
                                                      ("rk", "rank"), ("nv", "versions"), ("kn", "kin"),
                                                      ("rl", "related")) if fact.get(f) not in (None, [])}},
                "items": items}
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        blocks.append((p.label, len(items), base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")))
    n = len(blocks)
    data_html = "\n".join(
        f'<script type="application/octet-stream" data-project="{html.escape(label)}" data-items="{count}">'
        f"{b64}</script>\n<script>__read({i},{n})</script>"
        for i, (label, count, b64) in enumerate(blocks, 1))
    fams = page_subjects((subjects or {}).get("families", []), pids, labels)
    if fams:
        raw = json.dumps(fams, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        data_html += ('\n<script type="application/octet-stream" data-subjects="1">'
                      + base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii") + "</script>")
        tps = page_topics((subjects or {}).get("topics"), (subjects or {}).get("families", []), fams, pids)
        if tps:
            raw = json.dumps(tps, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            data_html += ('\n<script type="application/octet-stream" data-topics="1">'
                          + base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii") + "</script>")
    if pictures:
        data_html += "\n" + "\n".join(f'<script type="application/octet-stream" data-sketch="{html.escape(i)}" '
                                       f'data-format="{fmt}">{b64}</script>' for i, fmt, b64 in pictures)
    page = _asset("search.html")
    for key, value in (("VERSION", html.escape(version)), ("TITLE", TITLE), ("MODELS", plural(n, "model")),
                       ("ITEMS", plural(n_items, "item")), ("CSS", _asset("search.css")), ("JS", _asset("search.js"))):
        page = page.replace("{{" + key + "}}", value)
    page = page.replace("{{DATA}}", data_html)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return {"projects": n, "items": n_items, "data bytes": sum(len(b) for _, _, b in blocks),
            "sketches": len(pictures), "sketch bytes": sum(len(b) for _, _, b in pictures)}

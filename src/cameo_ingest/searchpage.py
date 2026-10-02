"""The catalog as one self-contained web page, searched in a browser opened from disk (plan KX-04).

The page holds its code (`assets/search.js`, `assets/search.css`, `assets/search.html`) and its
data: one block per project, base64 of gzipped JSON, which the page unpacks, indexes and
searches (BM25, as the retrieval evaluation measured), showing what it is doing as it loads.
It loads nothing from the network.

Each project's block holds `project` (label, file name, token, sources, counts) and `items`,
objects with short keys to keep the page small:

    k key   t type   kd kind   id requirement id   db database number   n name   w where
    x text (requirement text, documentation, summary)   c the item's chunks, as the RAG reads them
    r relations [kind, direction, phrase, other key, other label]   d diagrams [key, label]
    l listed in [key, label] (a member, which borrows its owner's chunks: not repeated here)
    m model (generated text)   of [key, label] (what a summary is of)
    sk the ids of a diagram's sketch blocks (`--sketches`), the whole diagram first

Sketches, when asked for (plan KX-05), follow in blocks of their own, decoded only when their
diagram is opened: `webp`, the tree's PNG sketches (and a large diagram's modules) re-encoded
losslessly; `svg`, the SVG sketches, gzipped.

Relationship records stay in the workbook: the page shows them on their items.
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


def page_items(p: ProjectCatalog, sketch_ids: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """The project's records as the page's items, each with its chunks' text."""
    out = []
    for r in p.records:
        t = r["type"]
        if t == "relationship":
            continue
        if t == "summary":
            it = {"k": r["key"], "t": t, "kd": r["label"], "n": f"{r['label']} of {r['of'][1]}", "x": r["text"],
                  "m": r.get("model"), "of": r["of"]}
            if "module" in r:
                it["n"] += f", module M{r['module']}"
            if "parts" in r:
                it["n"] += f", parts {r['parts'][0]}–{r['parts'][1]}"
        else:
            it = {"k": r["key"], "t": t, "kd": r.get("kind"), "id": r.get("id"), "db": r.get("db"), "n": r["name"],
                  "w": r.get("where"), "x": r.get("text"),
                  "r": [rel[1:] for rel in r.get("relations", [])], "d": r.get("diagrams"), "l": r.get("listed_in")}
            if not r.get("listed_in"):
                it["c"] = "\n\n".join(p.chunks[c] for c in r.get("chunks", []) if c in p.chunks)
            if sketch_ids and r["key"] in sketch_ids:
                it["sk"] = sketch_ids[r["key"]]
        out.append({k: v for k, v in it.items() if v not in (None, "", [])})
    return out


def write_search_page(path: Path, projects: Iterable[ProjectCatalog], version: str,
                      sketches: str = "none") -> dict[str, int]:
    """Write the page; returns its counts (projects, items, bytes of data, sketches)."""
    blocks: list[tuple[str, int, str]] = []
    pictures: list[tuple[str, str, str]] = []
    n_items = 0
    for pid, p in enumerate(projects):
        sketch_ids: dict[str, list[str]] = {}
        for r in p.records:
            if r["type"] == "diagram" and (found := sketch_blocks(p, pid, r, sketches)):
                sketch_ids[r["key"]] = [i for i, _, _ in found]
                pictures += found
        items = page_items(p, sketch_ids)
        n_items += len(items)
        data = {"project": {"label": p.label, "name": p.header.get("name"), "token": p.header.get("token"),
                            "sources": p.sources, "counts": p.header.get("counts", {})},
                "items": items}
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        blocks.append((p.label, len(items), base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")))
    n = len(blocks)
    data_html = "\n".join(
        f'<script type="application/octet-stream" data-project="{html.escape(label)}" data-items="{count}">'
        f"{b64}</script>\n<script>__read({i},{n})</script>"
        for i, (label, count, b64) in enumerate(blocks, 1))
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

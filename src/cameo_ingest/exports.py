"""The root files of an output tree, rebuilt from state.sqlite at the end of every run
(plan RI-05). They cover every project in the tree, not only the latest run's.

    INDEX.md          every project: name, token, counts, where it was found; failures
    manifest.json     every written project: token, directory, summary, files with sha256
    provenance.jsonl  one record per token: its sightings, with input paths, archive
                      chains and --meta values (the lookup behind a project's token)
    chunks.jsonl      all projects' chunks, with each project's --meta values joined in
                      (`metadata.source_metadata`: key -> sorted list of values)
    rag/              the same chunks as files, for RAG tools that read files rather than
                      JSONL: text/<project>/<sha256>.txt (.md for Markdown chunks), each
                      ending with a source line (project and trace), and meta/<project>/
                      <sha256>.json, each file's metadata

Only provenance.jsonl names local paths; the others name inputs by file name.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from . import plain as pl
from .ledger import _MD_LINK, MAX_CHARS, MAX_ROWS
from .provenance import TOOL, sha256_bytes, sha256_text
from .state import State
from .text import front_matter, md_inline, md_plain

PROJECTS = "by-sha256"
INDEX = "INDEX.md"
RAG = "rag"
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f`]+')  # not in file names, on Windows or elsewhere


def sightings(state: State, sha256: str) -> list[dict[str, Any]]:
    return [{"path": s["path"], "input_sha256": s["input_sha256"], "chain": json.loads(s["chain"]),
             "metadata": json.loads(s["metadata"]), "missing": s["input_status"] == "missing"}
            for s in state.sightings(sha256)]


def _found_in(seen: list[dict[str, Any]]) -> str:
    """Where a content was found, by input file name and archive chain (no local paths)."""
    places = []
    for s in seen:
        place = "!".join([PurePosixPath(s["path"]).name, *s["chain"]])
        meta = ", ".join(f"{k}={v}" for k, v in s["metadata"].items())
        places.append(f"`{place}`" + (f" ({meta})" if meta else "") + (" (input missing)" if s["missing"] else ""))
    return "; ".join(dict.fromkeys(places)) or "no current input"


def _merged_metadata(seen: list[dict[str, Any]]) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {}
    for s in seen:
        for k, v in s["metadata"].items():
            merged.setdefault(k, set()).add(str(v))
    return {k: sorted(v) for k, v in sorted(merged.items())}


def rebuild(state: State, out: Path) -> None:
    rows = state.db.execute("SELECT * FROM project_status ORDER BY name, sha256").fetchall()
    written = {r["content_sha256"]: r for r in state.written()}
    seen = {r["sha256"]: sightings(state, r["sha256"]) for r in rows}

    manifest: dict[str, Any] = {"tool": TOOL, "projects": [], "failed": []}
    for sha, p in written.items():
        manifest["projects"].append({
            "token": f"sha256:{sha}", "dir": f"{PROJECTS}/{sha}", "name": p["name"],
            "summary": json.loads(p["summary"]),
            "files": [{"path": f["path"], "sha256": f["sha256"]} for f in state.files(sha)],
        })
    manifest["failed"] = [{"token": f"sha256:{r['sha256']}", "name": r["name"], "error": r["error"]}
                          for r in rows if r["status"] == "failed"]
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    with (out / "provenance.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"token": f"sha256:{r['sha256']}", "name": r["name"], "status": r["status"],
                                "sightings": seen[r["sha256"]]}, ensure_ascii=False) + "\n")

    index_rows = []  # (token, markdown row)
    for sha, p in written.items():
        s = json.loads(p["summary"])
        version = s.get("exporter", {}).get("exporterVersion", "unknown version")
        index_rows.append((f"sha256:{sha}", (
            f"- [{md_inline(p['name'])}]({PROJECTS}/{sha}/README.md) ([ledger]({PROJECTS}/{sha}/LEDGER.md)) "
            f"`sha256:{sha[:16]}`: saved by {version}; {s['elements']} elements, {s['diagrams']} diagrams, "
            f"{s['requirements']} requirements; found in {_found_in(seen[sha])}")))
    lines = ["# Cameo projects in this output tree", "",
             (f"{len(written)} project(s) written. Each project's directory is named by its content token "
              f"(`{PROJECTS}/<sha256>`). Where each was found is listed below by file name, and with full "
              "paths and `--meta` values in `provenance.jsonl`."), "", "## Projects", ""]
    lines += [row for _, row in index_rows] or ["None yet."]
    others = [r for r in rows if r["status"] != "written"]
    if others:
        lines += ["", "## Not written", ""]
        lines += [f"- {md_inline(r['name'])} `sha256:{r['sha256'][:16]}`: {r['status']}"
                  + (f" ({r['error']})" if r["error"] else "") + f"; found in {_found_in(seen[r['sha256']])}"
                  for r in others]
    fm = front_matter({"title": "Cameo projects in this output tree", "kind": "index",
                       "provenance": {"tool": TOOL, "state": "state.sqlite", "projects": len(written)}})
    (out / INDEX).write_text(fm + "\n".join(lines) + "\n", encoding="utf-8")

    with (out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for sha in written:
            meta = _merged_metadata(seen[sha])
            with (out / PROJECTS / sha / "index" / "chunks.jsonl").open(encoding="utf-8") as src:
                for line in src:
                    c = json.loads(line)
                    c["metadata"]["file"] = f"{PROJECTS}/{sha}/{c['metadata']['file']}"
                    c["metadata"]["source_metadata"] = meta
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
        for c in _projects_ledger(index_rows):
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    settings = state.settings()
    if settings.get("rag_files", True):
        write_rag(out, {sha: p["name"] for sha, p in written.items()}, {sha: _merged_metadata(seen[sha]) for sha in written},
                  _projects_ledger(index_rows), ".md" if settings.get("chunk_style") == "markdown" else ".txt")
    elif (out / RAG).exists():
        shutil.rmtree(out / RAG)


def _safe(name: str, limit: int = 80) -> str:
    """A file name part: no characters that file systems refuse, at most `limit` characters."""
    name = " ".join(_UNSAFE.sub(" ", name).split()).strip(" .")
    return name if len(name) <= limit else name[:limit].rsplit(" ", 1)[0].rstrip(" .")


def rag_text(chunk: dict[str, Any], project: str | None, found_with: dict[str, list[str]]) -> str:
    """A chunk as a file: its text, then where it came from. A RAG tool that reads files may
    keep only their text, so the provenance goes in it as well as in the metadata file: the
    project and the trace locator (which names the content, archive entry, element and line),
    and the --meta values of the inputs it was found in. One short line, since every token of
    it is one fewer for the text: the plain style leaves room for it within a 512-token window."""
    meta = chunk["metadata"]
    locator = (meta.get("provenance") or {}).get("locator")
    source = "; ".join(x for x in (project, f"trace {locator}" if locator else None) if x)
    lines = [chunk["text"].rstrip(), "", f"Source: {source}"]
    if found_with:
        lines.append("Found with: " + "; ".join(f"{k}={', '.join(v)}" for k, v in sorted(found_with.items())))
    return "\n".join(lines) + "\n"


def rag_meta(chunk: dict[str, Any], file: str, sha: str | None, project: str | None,
             found_with: dict[str, list[str]]) -> dict[str, Any]:
    """The metadata file of a chunk's file: flat, for tools that take metadata per file. The
    chunk's id joins it to chunks.jsonl, which has the rest."""
    m = chunk["metadata"]
    prov = m.get("provenance") or {}
    d = prov.get("derivation") or {}
    page = m.get("file")
    out: dict[str, Any] = {
        "file": file, "title": md_plain(chunk["text"].split("\n", 1)[0].lstrip("# ")), "chunk_id": chunk["id"],
        "kind": m.get("kind"), "project": project, "project_token": m.get("content"),
        "element_id": m.get("element_id"), "element_type": m.get("element_type"),
        "qualified_name": m.get("qualified_name"), "stereotypes": m.get("stereotypes") or None,
        "page": f"{PROJECTS}/{sha}/{page}" if sha and page else page, "trace": prov.get("locator"),
        "derivation": d.get("method"), "generated_by": d.get("model"), "tool": d.get("tool"),
        "found_with": found_with or None,
    }
    for k in ("part", "parts", "piece", "pieces", "diagram_type"):
        if isinstance(m.get(k), (str, int)):
            out[k] = m[k]
    return {k: v for k, v in out.items() if v is not None}


def _write_files(folder: str, root: Path, chunks: list[dict[str, Any]], sha: str | None, project: str | None,
                 found_with: dict[str, list[str]], ext: str) -> None:
    """A folder of chunk files under text/, named by the sha256 of their text, and their
    metadata under meta/, at the same path. Two chunks with the same text share a file, and its
    metadata lists both."""
    text_dir, meta_dir = root / "text" / folder, root / "meta" / folder
    for d in (text_dir, meta_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    metas: dict[str, dict[str, Any]] = {}
    for c in chunks:
        data = rag_text(c, project, found_with).encode("utf-8")
        name = sha256_bytes(data)
        if name in metas:
            metas[name].setdefault("same_text_chunk_ids", []).append(c["id"])
            continue
        (text_dir / f"{name}{ext}").write_bytes(data)
        metas[name] = rag_meta(c, f"{name}{ext}", sha, project, found_with)
    for name, record in metas.items():
        (meta_dir / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def write_rag(out: Path, names: dict[str, str], found_with: dict[str, dict[str, list[str]]],
              tree_chunks: list[dict[str, Any]], ext: str) -> None:
    """rag/: the chunks as files, for RAG tools that read files. Under text/, a folder per
    project (its name and token, `TMT-9ffd7a2c`) of files named by the sha256 of their text;
    under meta/, the same folders, with each file's metadata as `<sha256>.json`; the projects
    ledger in `_tree`. Point a RAG tool at text/ alone. A project's files are written again only
    when its chunks or --meta values change; folders of projects no longer in the tree go."""
    root = out / RAG
    for d in (root, root / "text", root / "meta"):
        d.mkdir(exist_ok=True)
    for old in root.iterdir():  # anything else is from an earlier layout
        if old.name not in ("text", "meta"):
            shutil.rmtree(old) if old.is_dir() else old.unlink()
    keep = {"_tree"}
    for sha, name in names.items():
        src = out / PROJECTS / sha / "index" / "chunks.jsonl"
        stamp = json.dumps([sha256_bytes(src.read_bytes()), found_with[sha], ext, TOOL])
        folder = f"{_safe(PurePosixPath(name).stem, 40)}-{sha[:8]}"
        keep.add(folder)
        marker = root / "meta" / folder / ".stamp"
        if marker.is_file() and marker.read_text(encoding="utf-8") == stamp and (root / "text" / folder).is_dir():
            continue
        with src.open(encoding="utf-8") as f:
            _write_files(folder, root, [json.loads(line) for line in f], sha, name, found_with[sha], ext)
        marker.write_text(stamp, encoding="utf-8")
    for top in (root / "text", root / "meta"):
        for old in top.iterdir():
            if old.name not in keep:
                shutil.rmtree(old) if old.is_dir() else old.unlink()
    _write_files("_tree", root, tree_chunks, None, None, {}, ext)


def _projects_ledger(index_rows: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """The index as `ledger:projects` chunks: one self-describing list, split like the
    per-project ledgers."""
    parts: list[list[tuple[str, str]]] = [[]]
    size = 0
    limit = min(MAX_CHARS, pl.BUDGET - pl.tokens("Projects ledger (part 99 of 99): the Cameo projects in this "
                                                 "output tree, 9999 in all.") - 4)  # in estimated tokens
    for token, row in index_rows:
        plain = md_plain(_MD_LINK.sub(r"\1", row))
        n = pl.tokens(plain) + 1
        if parts[-1] and (len(parts[-1]) >= MAX_ROWS or size + n > limit):
            parts.append([])
            size = 0
        parts[-1].append((token, plain))
        size += n
    chunks = []
    for i, part in enumerate(parts, 1):
        if not part:
            continue
        of = f" (part {i} of {len(parts)})" if len(parts) > 1 else ""
        text = (f"Projects ledger{of}: the Cameo projects in this output tree, {len(index_rows)} in all.\n\n"
                + "\n".join(r for _, r in part))
        chunks.append({
            "id": sha256_text(f"ledger:projects|{i}")[:24],
            "title": f"Cameo projects in this output tree{of}",
            "text": text,
            "metadata": {"kind": "ledger:projects", "file": INDEX, "entries": len(part),
                         "tokens": [t for t, _ in part],
                         "provenance": {"derivation": {"method": "extracted", "tool": TOOL}, "locator": INDEX}},
        })
    return chunks

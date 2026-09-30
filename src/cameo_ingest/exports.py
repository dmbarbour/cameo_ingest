"""The root files of an output tree, rebuilt from state.sqlite at the end of every run
(plan RI-05). They cover every project in the tree, not only the latest run's.

    INDEX.md          every project: name, token, counts, where it was found; failures
    manifest.json     every written project: token, directory, summary, files with sha256
    provenance.jsonl  one record per token: its sightings, with input paths, archive
                      chains and --meta values (the lookup behind a project's token)
    chunks.jsonl      all projects' chunks, with each project's --meta values joined in
                      (`metadata.source_metadata`: key -> sorted list of values)

Only provenance.jsonl names local paths; the others name inputs by file name.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from .ledger import _MD_LINK, MAX_CHARS, MAX_ROWS
from .provenance import TOOL, sha256_text
from .state import State
from .text import front_matter, md_inline, md_plain

PROJECTS = "by-sha256"
INDEX = "INDEX.md"


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


def _projects_ledger(index_rows: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """The index as `ledger:projects` chunks: one self-describing list, split like the
    per-project ledgers."""
    parts: list[list[tuple[str, str]]] = [[]]
    size = 0
    for token, row in index_rows:
        plain = md_plain(_MD_LINK.sub(r"\1", row))
        if parts[-1] and (len(parts[-1]) >= MAX_ROWS or size + len(plain) > MAX_CHARS):
            parts.append([])
            size = 0
        parts[-1].append((token, plain))
        size += len(plain)
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

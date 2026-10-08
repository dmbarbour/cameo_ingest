"""The root files of an output tree, rebuilt from state.sqlite at the end of every run
(plan RI-05). They cover every project in the tree, not only the latest run's.

    INDEX.md          every project: name, token, counts, where it was found; failures
    manifest.json     every written project: token, directory, summary, files with sha256
    provenance.jsonl  one record per token: its sightings, with input paths, archive
                      chains and --meta values (the lookup behind a project's token)
    chunks.jsonl      all projects' chunks, with each project's --meta values joined in
                      (`metadata.source_metadata`: key -> sorted list of values)
    CROSSREF.md       identifiers (requirement ids, ids in text) held by two elements or more,
                      across every model, with each place (plan RF-03); also as index:id chunks.
                      Each model's derivation trees (RF-05), made with the project, join its
                      chunks as trace:thread chunks, as do its type hierarchies (TH) as index:hierarchy chunks
    rag/              the same chunks as files, for RAG tools that read files rather than
                      JSONL: text/<project>/<sha256>.txt, each
                      ending with a source line (project and trace), and meta/<project>/
                      <sha256>.json, each file's metadata

Only provenance.jsonl and rag/meta name local paths; the others name inputs by file name.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import chunks, crossref, hierarchies
from . import plain as pl
from . import threads as threads_mod
from .config import TreeSettings
from .ledger import MAX_ROWS
from .provenance import TOOL, ContentInfo, chunk_ref, sha256_bytes, short_id
from .state import State
from .text import front_matter, md_inline
from .treefiles import PROJECTS, index_file, project_dir, read_jsonl

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


@dataclass(frozen=True)
class Assembly:
    """What the tree's own chunks bring together, beyond each project's. Fixed defaults, measured
    (ADR-0027): users don't set them. A developer varies them to measure a change
    (`scripts/assemble_tree.py`), and the next run puts the defaults back."""

    cross_index: bool = True  # the index of identifiers across models (plan RF, ADR-0019)
    threads: bool = True  # requirement threads (plan RF, ADR-0019)
    hierarchies: bool = True  # type hierarchies (plan TH, ADR-0026)
    line_refs: bool = False  # a chunk reference on each line: it costs completeness (plan RF)
    # Kinds that stay out of rag/, as globs. None since 0.20.0: the LLM says what a package or diagram
    # is about (ADR-0029), where it listed names that crowded out answers (ADR-0028).
    rag_without: tuple[str, ...] = ()


@dataclass
class Tree:
    """What the root files are made from: every project's status, the written ones, where each
    was found, the tree's settings, and what its chunks bring together."""

    out: Path
    rows: list[Any]  # project_status
    written: dict[str, Any]  # content sha256 -> its row
    seen: dict[str, list[dict[str, Any]]]  # content sha256 -> its sightings
    settings: TreeSettings
    assembly: Assembly = field(default_factory=Assembly)


def rebuild(state: State, out: Path, assembly: Assembly | None = None, with_subjects: bool = True) -> None:
    """Every root file, one function each (AR-014R1). `subjects.json` without the LLM, keeping what a
    run found for unchanged families (`with_subjects`: a finished run has written it already)."""
    rows = state.project_rows()
    tree = Tree(out, rows, {r["content_sha256"]: r for r in state.written()},
                {r["sha256"]: sightings(state, r["sha256"]) for r in rows}, TreeSettings.from_stored(state.settings()),
                assembly or Assembly())
    write_manifest(tree, state)
    write_provenance(tree)
    index_rows = write_index_page(tree)
    tree_chunks = projects_ledger(index_rows) + cross_index(tree)
    threads = thread_chunks(tree)
    for sha, cs in hierarchy_chunks(tree).items():  # assembled as threads are (plan TH)
        threads[sha] = threads.get(sha, []) + cs
    write_chunks(tree, threads, tree_chunks)
    if tree.settings.rag_files:
        projects = [RagProject(sha, p["name"], _merged_metadata(tree.seen[sha]),
                               [_file_ref(s) for s in tree.seen[sha] if not s["missing"]]
                               or [_file_ref(s) for s in tree.seen[sha]])
                    for sha, p in tree.written.items()]
        write_rag(out, projects, tree_chunks, tree.settings.rag_source, threads, tree.assembly.rag_without)
    elif (out / RAG).exists():
        shutil.rmtree(out / RAG)
    if with_subjects:
        from . import subjects

        subjects.update(state, out)


def write_manifest(tree: Tree, state: State) -> None:
    manifest: dict[str, Any] = {"tool": TOOL, "projects": [], "failed": []}
    for sha, p in tree.written.items():
        manifest["projects"].append({
            "token": f"sha256:{sha}", "dir": f"{PROJECTS}/{sha}", "name": p["name"],
            "summary": json.loads(p["summary"]),
            "files": [{"path": f["path"], "sha256": f["sha256"]} for f in state.files(sha)],
        })
    manifest["failed"] = [{"token": f"sha256:{r['sha256']}", "name": r["name"], "error": r["error"]}
                          for r in tree.rows if r["status"] == "failed"]
    (tree.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


def write_provenance(tree: Tree) -> None:
    with (tree.out / "provenance.jsonl").open("w", encoding="utf-8") as f:
        for r in tree.rows:
            f.write(json.dumps({"token": f"sha256:{r['sha256']}", "name": r["name"], "status": r["status"],
                                "sightings": tree.seen[r["sha256"]]}, ensure_ascii=False) + "\n")


def write_index_page(tree: Tree) -> list[tuple[str, str]]:
    """INDEX.md; returns its rows, (token, Markdown row), for the projects ledger."""
    index_rows = []
    for sha, p in tree.written.items():
        s = json.loads(p["summary"])
        version = s.get("exporter", {}).get("exporterVersion", "unknown version")
        index_rows.append((f"sha256:{sha}", (
            f"- [{md_inline(p['name'])}]({PROJECTS}/{sha}/README.md) ([ledger]({PROJECTS}/{sha}/LEDGER.md)) "
            f"`sha256:{sha[:16]}`: saved by {version}; {s['elements']} elements, {s['diagrams']} diagrams, "
            f"{s['requirements']} requirements; found in {_found_in(tree.seen[sha])}")))
    lines = ["# Cameo projects in this output tree", "",
             (f"{len(tree.written)} project(s) written. Each project's directory is named by its content token "
              f"(`{PROJECTS}/<sha256>`). Where each was found is listed below by file name, and with full "
              "paths and `--meta` values in `provenance.jsonl`."), "", "## Projects", ""]
    lines += [row for _, row in index_rows] or ["None yet."]
    others = [r for r in tree.rows if r["status"] != "written"]
    if others:
        lines += ["", "## Not written", ""]
        lines += [f"- {md_inline(r['name'])} `sha256:{r['sha256'][:16]}`: {r['status']}"
                  + (f" ({r['error']})" if r["error"] else "") + f"; found in {_found_in(tree.seen[r['sha256']])}"
                  for r in others]
    fm = front_matter({"title": "Cameo projects in this output tree", "kind": "index",
                       "provenance": {"tool": TOOL, "state": "state.sqlite", "projects": len(tree.written)}})
    (tree.out / INDEX).write_text(fm + "\n".join(lines) + "\n", encoding="utf-8")

    return index_rows


def cross_index(tree: Tree) -> list[dict[str, Any]]:
    """The index of identifiers across the models (plan RF-03): CROSSREF.md, and its entries as
    chunks; or neither, when the tree's setting is off."""
    if not tree.assembly.cross_index:
        if (tree.out / crossref.FILE).exists():
            (tree.out / crossref.FILE).unlink()
        return []
    merged: dict[str, list[crossref.Place]] = defaultdict(list)
    for sha, p in tree.written.items():
        for term, ps in crossref.places(project_dir(tree.out, sha), ContentInfo(sha, p["name"])).items():
            merged[term] += ps
    fm = front_matter({"title": "Identifiers across the models in this tree", "kind": "crossref",
                       "provenance": {"tool": TOOL, "derivation": "assembled", "projects": len(tree.written)}})
    (tree.out / crossref.FILE).write_text(fm + crossref.page(merged), encoding="utf-8")
    return crossref.entries(merged, refs=tree.assembly.line_refs)


def thread_chunks(tree: Tree) -> dict[str, list[dict[str, Any]]]:
    """Each project's threads (plan RF-05), as chunks, by content sha256: made at build time with
    the project, included when the tree's setting is on (AR-014R2)."""
    if not tree.assembly.threads:
        return {}
    out = {}
    for sha, p in tree.written.items():
        records = read_jsonl(index_file(project_dir(tree.out, sha), "threads"), missing_ok=True)
        out[sha] = threads_mod.thread_chunks(records, ContentInfo(sha, p["name"]),
                                          refs=tree.assembly.line_refs)
    return out


def hierarchy_chunks(tree: Tree) -> dict[str, list[dict[str, Any]]]:
    """Each project's type hierarchies (plan TH), as chunks, by content sha256: made at build time
    with the project, included when the tree's setting is on."""
    if not tree.assembly.hierarchies:
        return {}
    out = {}
    for sha, p in tree.written.items():
        records = read_jsonl(index_file(project_dir(tree.out, sha), "hierarchies"), missing_ok=True)
        out[sha] = hierarchies.hierarchy_chunks(records, ContentInfo(sha, p["name"]), refs=tree.assembly.line_refs)
    return out


def write_chunks(tree: Tree, threads: dict[str, list[dict[str, Any]]], tree_chunks: list[dict[str, Any]]) -> None:
    """chunks.jsonl: each project's chunks and threads, with its --meta values; then the tree's own."""
    with (tree.out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for sha in tree.written:
            meta = _merged_metadata(tree.seen[sha])
            for c in read_jsonl(index_file(project_dir(tree.out, sha), "chunks")) + threads.get(sha, []):
                c = {**c, "metadata": {**c["metadata"], "file": f"{PROJECTS}/{sha}/{c['metadata']['file']}",
                                       "source_metadata": meta}}
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        for c in tree_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


@dataclass
class RagProject:
    """A written project, as rag/ names its sources."""

    sha: str
    name: str
    found_with: dict[str, list[str]]  # the --meta values of its inputs
    files: list[str]  # where it was found: absolute paths, with archive chains ("/x/a.zip!b.mdzip")

    @property
    def id(self) -> str:
        """Its short logical id: the start of its token, as in its folder's name."""
        return short_id(self.sha)


def _file_ref(sighting: dict[str, Any]) -> str:
    return "!".join([sighting["path"], *sighting["chain"]])


def _safe(name: str, limit: int = 80) -> str:
    """A file name part: no characters that file systems refuse, at most `limit` characters."""
    name = " ".join(_UNSAFE.sub(" ", name).split()).strip(" .")
    return name if len(name) <= limit else name[:limit].rsplit(" ", 1)[0].rstrip(" .")


def rag_text(chunk: dict[str, Any], project: RagProject | None, form: str = "trace") -> str:
    """A chunk as a file: its text, then where it came from. A RAG tool that reads files may
    keep only their text, so the source goes in it as well as in the metadata file. The chunk's
    heading already names the project, by its label ("TMT [9ffd7a2c]"); the source line adds,
    in one of two forms (`--rag-source`):
    - `trace`: the trace locator (content, archive entry, element and line);
    - `id`: only the short ids of the project and the chunk ("[9ffd7a2c:14d101e0b1d2]"), which
      rag/meta/_sources.json and chunks.jsonl resolve to the input files and the locator.
    Never the input files' names or paths, which can be longer than a whole window, and repeat.
    Then the --meta values of the inputs it was found in."""
    meta = chunk["metadata"]
    locator = (meta.get("provenance") or {}).get("locator")
    if project is not None and form == "id":
        source = f"[{chunk_ref(project.sha, chunk['id'])}]"
    else:
        source = locator
    lines = [chunk["text"].rstrip(), ""] + ([f"Source: {source}"] if source else [])
    if project is not None and project.found_with:
        lines.append("Found with: " + "; ".join(f"{k}={', '.join(v)}" for k, v in sorted(project.found_with.items())))
    return "\n".join(lines) + "\n"


def rag_meta(chunk: dict[str, Any], file: str, project: RagProject | None) -> dict[str, Any]:
    """The metadata file of a chunk's file: flat, for tools that take metadata per file. The
    chunk's id joins it to chunks.jsonl, which has the rest."""
    m = chunk["metadata"]
    prov = m.get("provenance") or {}
    d = prov.get("derivation") or {}
    page = m.get("file")
    out: dict[str, Any] = {
        "file": file, "title": pl.plain(chunk["text"].split("\n", 1)[0].lstrip("# ")), "chunk_id": chunk["id"],
        "kind": m.get("kind"), "project": project.name if project else None, "project_token": m.get("content"),
        "source_id": project.id if project else None,
        "source_file": project.files[0] if project else None, "source_files": project.files if project else None,
        "element_id": m.get("element_id"), "element_type": m.get("element_type"),
        "qualified_name": m.get("qualified_name"), "stereotypes": m.get("stereotypes") or None,
        "page": f"{PROJECTS}/{project.sha}/{page}" if project and page else page, "trace": prov.get("locator"),
        "derivation": d.get("method"), "generated_by": d.get("model"), "tool": d.get("tool"),
        "found_with": (project.found_with or None) if project else None,
    }
    for k in ("part", "parts", "piece", "pieces", "diagram_type", "about_class"):
        if isinstance(m.get(k), (str, int)):
            out[k] = m[k]
    return {k: v for k, v in out.items() if v is not None}


def _write_files(folder: str, root: Path, chunks: list[dict[str, Any]], project: RagProject | None, form: str) -> None:
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
        data = rag_text(c, project, form).encode("utf-8")
        name = sha256_bytes(data)
        if name in metas:
            metas[name].setdefault("same_text_chunk_ids", []).append(c["id"])
            continue
        (text_dir / f"{name}.txt").write_bytes(data)
        metas[name] = rag_meta(c, f"{name}.txt", project)
    for name, record in metas.items():
        (meta_dir / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def write_rag(out: Path, projects: list[RagProject], tree_chunks: list[dict[str, Any]], form: str = "trace",
              threads: dict[str, list[dict[str, Any]]] | None = None, without: tuple[str, ...] = ()) -> None:
    """rag/: the chunks as files, for RAG tools that read files. Under text/, a folder per
    project (its name and short id, `TMT-9ffd7a2c`) of files named by the sha256 of their text;
    under meta/, the same folders, with each file's metadata as `<sha256>.json`, and
    `_sources.json`, which resolves each project's short id to the files it was found in; the
    projects ledger in `_tree`. Point a RAG tool at text/ alone. Chunks of the kinds `without`
    (globs) are left out. A project's files are written again only when its chunks, sources,
    --meta values or the kinds left out change; folders of projects no longer in the tree go."""
    root = out / RAG
    for d in (root, root / "text", root / "meta"):
        d.mkdir(exist_ok=True)
    for old in root.iterdir():  # anything else is from an earlier layout
        if old.name not in ("text", "meta"):
            shutil.rmtree(old) if old.is_dir() else old.unlink()
    keep, sources = {"_tree", "_sources.json"}, {}
    for p in projects:
        src = index_file(project_dir(out, p.sha), "chunks")
        extra = (threads or {}).get(p.sha, [])  # the project's threads, when the tree includes them
        stamp = json.dumps([sha256_bytes(src.read_bytes()), p.found_with, p.files, ".txt", form, TOOL,
                            sha256_bytes(json.dumps(extra, sort_keys=True).encode()), list(without)])
        folder = f"{_safe(PurePosixPath(p.name).stem, 40)}-{p.id}"
        keep.add(folder)
        sources[p.id] = {"project": p.name, "token": f"sha256:{p.sha}", "folder": folder, "files": p.files,
                         "found_with": p.found_with}
        marker = root / "meta" / folder / ".stamp"
        if marker.is_file() and marker.read_text(encoding="utf-8") == stamp and (root / "text" / folder).is_dir():
            continue
        with src.open(encoding="utf-8") as f:
            cs = [c for c in map(json.loads, f) if not any(fnmatch.fnmatchcase(c["metadata"]["kind"], g) for g in without)]
        _write_files(folder, root, cs + extra, p, form)
        marker.write_text(stamp, encoding="utf-8")
    for top in (root / "text", root / "meta"):
        for old in top.iterdir():
            if old.name not in keep:
                shutil.rmtree(old) if old.is_dir() else old.unlink()
    _write_files("_tree", root, tree_chunks, None, form)
    (root / "meta" / "_sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")


def projects_ledger(index_rows: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """The index as `ledger:projects` chunks: one self-describing list, split like the
    per-project ledgers."""
    parts = pl.pack([(token, pl.plain(row)) for token, row in index_rows],
                    "Projects ledger (part 99 of 99): the Cameo projects in this output tree, 9999 in all.",
                    max_rows=MAX_ROWS)
    out = []
    for i, part in enumerate(parts, 1):
        of = f" (part {i} of {len(parts)})" if len(parts) > 1 else ""
        text = (f"Projects ledger{of}: the Cameo projects in this output tree, {len(index_rows)} in all.\n\n"
                + "\n".join(r for _, r in part))
        out.append(chunks.make(("ledger:projects", str(i)), f"Cameo projects in this output tree{of}", text, {
            "kind": "ledger:projects", "file": INDEX, "entries": len(part), "tokens": [t for t, _ in part],
            "provenance": {"derivation": {"method": "extracted", "tool": TOOL}, "locator": INDEX}}))
    return out

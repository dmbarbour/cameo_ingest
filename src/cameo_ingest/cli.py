"""Command line entry point: `cameo-ingest SOURCE -o OUTDIR [--meta k=v ...]`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .archive import UnsupportedInput, discover
from .llm import LLM, LLMConfig
from .pipeline import ingest_project
from .provenance import RunInfo, SourceInfo, Trace, sha256_bytes, sha256_text, utc_now
from .text import front_matter, slug

log = logging.getLogger("cameo_ingest")


def _parse_meta(pairs: list[str], files: list[str]) -> dict:
    meta: dict = {}
    for f in files:
        meta.update(json.loads(Path(f).read_text(encoding="utf-8")))
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"--meta expects KEY=VALUE, got {p!r}")
        k, v = p.split("=", 1)
        meta[k.strip()] = v
    return meta


def write_root_ledger(out: Path, run: RunInfo, projects: list[dict]) -> dict:
    """Top-level LEDGER.md: which projects this source file contained, and where."""
    src = run.source
    lines = [f"# Ledger: {Path(src.path).name}", "",
             f"Source file `{src.path}` (sha256 `{src.sha256}`) contains {len(projects)} Cameo project(s).", ""]
    if src.metadata:
        lines += ["Source metadata: " + ", ".join(f"{k}={v}" for k, v in src.metadata.items()), ""]
    for p in projects:
        lines.append(f"- [{p['name']}]({p['dir']}/LEDGER.md) — archive path `{'!'.join(p['container'])}`; "
                     f"saved by {p['exporter'].get('exporterVersion', 'unknown version')}; "
                     f"{p['elements']} elements, {p['diagrams']} diagrams, {p['requirements']} requirements")
    text = "\n".join(lines) + "\n"
    trace = Trace(source_sha256=src.sha256)
    fm = front_matter({"title": f"Ledger {Path(src.path).name}", "kind": "ledger",
                       "provenance": {"source_path": src.path, "source_sha256": src.sha256,
                                      "source_metadata": src.metadata, "run_id": run.run_id,
                                      "tool": run.tool, "trace": trace.to_dict()}})
    (out / "LEDGER.md").write_text(fm + text, encoding="utf-8")
    return {
        "id": sha256_text(f"{src.sha256}|ledger:projects")[:24],
        "title": f"Projects in {Path(src.path).name}",
        "text": text,
        "metadata": {"kind": "ledger:projects", "file": "LEDGER.md", "source_metadata": src.metadata,
                     "provenance": trace.to_dict()},
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cameo-ingest",
        description="Convert a Cameo/MagicDraw project (.mdzip, .mdzipx, .mdxml, or a bundle such as .rdzip "
                    "containing them) into provenance-tagged Markdown, CSV and JSON for RAG ingestion.",
        epilog="LLM enrichment is enabled only when a model is named (--text-model or CAMEO_INGEST_TEXT_MODEL); "
               "it uses OPENAI_API_KEY / OPENAI_BASE_URL. Model content is then sent to that endpoint. "
               "Exit status: 0 success; 2 usage error or non-empty output directory; 3 no model found or "
               "unsupported input; 4 some projects failed (the others are written; see manifest.json).",
    )
    ap.add_argument("source", type=Path, help="input file")
    ap.add_argument("-o", "--out", type=Path, required=True, help="output directory (created if missing)")
    ap.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                    help="provenance metadata recorded with every output (repeatable)")
    ap.add_argument("--meta-file", action="append", default=[], metavar="JSON",
                    help="JSON object of provenance metadata (repeatable; --meta wins)")
    ap.add_argument("--text-model", help="LLM for summaries (overrides CAMEO_INGEST_TEXT_MODEL)")
    ap.add_argument("--vision-model", help="LLM for image descriptions (overrides CAMEO_INGEST_VISION_MODEL)")
    ap.add_argument("--no-llm", action="store_true", help="disable LLM enrichment even if configured")
    ap.add_argument("--no-render", action="store_true", help="do not render diagram images")
    ap.add_argument("--cache-dir", type=Path, help="LLM response cache (default: OUT/.cache)")
    ap.add_argument("--force", action="store_true", help="allow writing into a non-empty output directory")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    ap.add_argument("--version", action="version", version=f"cameo-ingest {__version__}")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING - 10 * args.verbose, format="%(levelname)s %(name)s: %(message)s")

    out: Path = args.out
    if out.exists() and any(p.name != ".cache" for p in out.iterdir()) and not args.force:
        print(f"error: output directory {out} is not empty (use --force)", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    data = args.source.read_bytes()
    source = SourceInfo(path=str(args.source), sha256=sha256_bytes(data), size=len(data),
                        metadata=_parse_meta(args.meta, args.meta_file))
    cfg = LLMConfig.from_env(args.text_model, args.vision_model)
    if args.no_llm:
        cfg.text_model = cfg.vision_model = None
    run = RunInfo(source=source, llm=cfg.public() if cfg.enabled else {})
    llm = LLM(cfg, args.cache_dir or out / ".cache" / "llm")

    try:
        projects = list(discover(data, args.source.name))
    except UnsupportedInput as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if not projects:
        print(f"error: no Cameo/XMI model found in {args.source}", file=sys.stderr)
        return 3

    manifest = {"run": run.to_dict(), "projects": [], "failed": [], "files": []}
    all_chunks = []
    used: set[str] = set()
    for proj in projects:
        name = slug("__".join(proj.container[1:] + (proj.name,)))
        while name.lower() in used:
            name += "_"
        used.add(name.lower())
        where = "!".join(proj.trace_container) or proj.name
        log.info("ingesting %s -> %s", where, name)
        try:
            result = ingest_project(run, proj, out / name, llm, render=not args.no_render)
        except Exception as e:  # one bad project must not stop the others (BASE-004)
            log.error("project %s failed: %s: %s", where, type(e).__name__, e)
            log.debug("traceback for %s", where, exc_info=True)
            manifest["failed"].append({"dir": name, "container": list(proj.trace_container),
                                       "error": f"{type(e).__name__}: {e}"})
            continue
        manifest["projects"].append({"dir": name, **result.summary})
        for f in result.outputs.files:
            manifest["files"].append({"path": str(f.relative_to(out)), "sha256": sha256_bytes(f.read_bytes())})
        for c in result.outputs.chunks:
            c["metadata"]["file"] = f"{name}/{c['metadata']['file']}"
            all_chunks.append(c)

    root_ledger = write_root_ledger(out, run, manifest["projects"])
    all_chunks.append(root_ledger)
    manifest["files"].append({"path": "LEDGER.md", "sha256": sha256_bytes((out / "LEDGER.md").read_bytes())})

    with (out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    manifest["run"]["finished"] = utc_now()
    manifest["run"]["llm_calls"] = llm.calls
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(projects)} project(s), {len(all_chunks)} chunks, {len(manifest['files'])} files -> {out}")
    if manifest["failed"]:
        print(f"error: {len(manifest['failed'])} of {len(projects)} project(s) failed; see manifest.json",
              file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())

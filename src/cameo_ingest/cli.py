"""Command line entry point: `cameo-ingest SOURCE -o OUTDIR [--meta k=v ...]`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .archive import UnsupportedInput, discover
from .emit import slug
from .llm import LLM, LLMConfig
from .pipeline import ingest_project
from .provenance import RunInfo, SourceInfo, sha256_bytes, utc_now

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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cameo-ingest",
        description="Convert a Cameo/MagicDraw project (.mdzip, .mdzipx, .mdxml, or a bundle such as .rdzip "
                    "containing them) into provenance-tagged Markdown, CSV and JSON for RAG ingestion.",
        epilog="LLM enrichment is enabled only when a model is named (--text-model or CAMEO_INGEST_TEXT_MODEL); "
               "it uses OPENAI_API_KEY / OPENAI_BASE_URL. Model content is then sent to that endpoint.",
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

    manifest = {"run": run.to_dict(), "projects": [], "files": []}
    all_chunks = []
    used: set[str] = set()
    for proj in projects:
        name = slug("__".join(proj.container[1:] + (proj.name,)))
        while name.lower() in used:
            name += "_"
        used.add(name.lower())
        log.info("ingesting %s -> %s", "!".join(proj.trace_container) or proj.name, name)
        result = ingest_project(run, proj, out / name, llm, render=not args.no_render)
        manifest["projects"].append({"dir": name, **result.summary})
        for f in result.outputs.files:
            manifest["files"].append({"path": str(f.relative_to(out)), "sha256": sha256_bytes(f.read_bytes())})
        for c in result.outputs.chunks:
            c["metadata"]["file"] = f"{name}/{c['metadata']['file']}"
            all_chunks.append(c)

    with (out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    manifest["run"]["finished"] = utc_now()
    manifest["run"]["llm_calls"] = llm.calls
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(projects)} project(s), {len(all_chunks)} chunks, {len(manifest['files'])} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command line entry point: `cameo-ingest SOURCE -o OUTDIR [--meta k=v ...]`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .archive import UnsupportedInput, discover
from .llm import LLM, LLMConfig
from .pipeline import ingest_project
from .progress import Progress
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


NO_MODEL = """error: no LLM model is configured. Either
  - pass --no-llm to ingest without LLM summaries and descriptions, or
  - name a model with --text-model / --vision-model, or set CAMEO_INGEST_TEXT_MODEL
    (or OPENAI_MODEL) in the environment or in a file loaded with --env FILE.
The endpoint comes from OPENAI_BASE_URL and OPENAI_API_KEY; see .env.example."""


PROGRESS_LOGGER = "cameo_ingest.progress"
_handlers: list[logging.Handler] = []  # ours, replaced when main() runs again (as in tests)


def setup_logging(verbose: int, log_file: Path | None) -> None:
    """Console at WARNING, INFO (-v) or DEBUG (-vv), plus progress lines at any level;
    `log_file` gets DEBUG whatever the console shows. Third-party libraries (openai,
    httpx) stay at WARNING below -vv."""
    root = logging.getLogger()
    for h in _handlers:
        root.removeHandler(h)
        h.close()
    _handlers.clear()
    console_level = logging.WARNING - 10 * min(verbose, 2)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(min(console_level, logging.INFO))
    console.addFilter(lambda r: r.levelno >= console_level or r.name == PROGRESS_LOGGER)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _handlers.append(console)
    if log_file is not None:
        f = logging.FileHandler(log_file, encoding="utf-8")
        f.setLevel(logging.DEBUG)
        f.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
        _handlers.append(f)
    for h in _handlers:
        root.addHandler(h)
    ours = logging.DEBUG if log_file is not None else console_level
    logging.getLogger("cameo_ingest").setLevel(ours)
    logging.getLogger(PROGRESS_LOGGER).setLevel(min(ours, logging.INFO))
    root.setLevel(logging.WARNING if verbose < 2 else logging.DEBUG)  # what other libraries log


def load_env(path: Path) -> None:
    """Load variables from a dotenv file. Variables already set in the environment win,
    as with python-dotenv's default. Values are never logged."""
    from dotenv import dotenv_values

    values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    loaded = [k for k in values if k not in os.environ]
    for k in loaded:
        os.environ[k] = values[k]
    kept = sorted(set(values) - set(loaded))
    log.info("loaded %s from %s%s", ", ".join(loaded) or "no variables", path,
             f"; already set, so not loaded: {', '.join(kept)}" if kept else "")


def write_root_ledger(out: Path, run: RunInfo, projects: list[dict]) -> dict:
    """Top-level LEDGER.md: which projects this source file contained, and where."""
    src = run.source
    lines = [f"# Ledger: {src.name}", "",
             f"Source file `{src.name}` (sha256 `{src.sha256}`) contains {len(projects)} Cameo project(s).", ""]
    if src.metadata:
        lines += ["Source metadata: " + ", ".join(f"{k}={v}" for k, v in src.metadata.items()), ""]
    for p in projects:
        lines.append(f"- [{p['name']}]({p['dir']}/LEDGER.md) — archive path `{'!'.join(p['container'])}`; "
                     f"saved by {p['exporter'].get('exporterVersion', 'unknown version')}; "
                     f"{p['elements']} elements, {p['diagrams']} diagrams, {p['requirements']} requirements")
    text = "\n".join(lines) + "\n"
    trace = Trace(source_sha256=src.sha256)
    fm = front_matter({"title": f"Ledger {src.name}", "kind": "ledger",
                       "provenance": {"source_name": src.name, "source_sha256": src.sha256,
                                      "source_metadata": src.metadata, "tool": run.tool,
                                      "trace": trace.to_dict()}})
    (out / "LEDGER.md").write_text(fm + text, encoding="utf-8")
    return {
        "id": sha256_text(f"{src.sha256}|ledger:projects")[:24],
        "title": f"Projects in {src.name}",
        "text": text,
        "metadata": {"kind": "ledger:projects", "file": "LEDGER.md", "source_metadata": src.metadata,
                     "provenance": trace.to_dict()},
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cameo-ingest",
        description="Convert a Cameo/MagicDraw project (.mdzip, .mdzipx, .mdxml, or a bundle such as .rdzip "
                    "containing them) into provenance-tagged Markdown, CSV and JSON for RAG ingestion.",
        epilog="Either name an LLM model (--text-model, CAMEO_INGEST_TEXT_MODEL or OPENAI_MODEL) or pass "
               "--no-llm. The LLM is reached through OPENAI_BASE_URL / OPENAI_API_KEY, and model content is "
               "sent to that endpoint. "
               "Exit status: 0 success; 2 usage or configuration error, or non-empty output directory; "
               "3 no model found or unsupported input; 4 some projects failed (the others are written; see "
               "manifest.json); 5 the LLM endpoint check failed.",
    )
    ap.add_argument("source", type=Path, help="input file")
    ap.add_argument("-o", "--out", type=Path, required=True, help="output directory (created if missing)")
    ap.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                    help="provenance metadata recorded with every output (repeatable)")
    ap.add_argument("--meta-file", action="append", default=[], metavar="JSON",
                    help="JSON object of provenance metadata (repeatable; --meta wins)")
    ap.add_argument("--env", type=Path, metavar="FILE",
                    help="load environment variables from a dotenv file (variables already set win)")
    ap.add_argument("--text-model", help="LLM for summaries (overrides CAMEO_INGEST_TEXT_MODEL, OPENAI_MODEL)")
    ap.add_argument("--vision-model", help="LLM for image descriptions (overrides CAMEO_INGEST_VISION_MODEL; "
                                           "default: the text model)")
    ap.add_argument("--no-llm", action="store_true", help="ingest without LLM enrichment (required when no "
                                                          "model is configured)")
    ap.add_argument("--no-preflight", action="store_true",
                    help="skip the check that each LLM model answers before parsing starts")
    ap.add_argument("--llm-timeout", type=float, metavar="SECONDS", help="per-request timeout (default 120)")
    ap.add_argument("--llm-retries", type=int, metavar="N", help="retries per request (default 2)")
    ap.add_argument("--llm-max-calls", type=int, metavar="N", help="stop calling the LLM after N requests "
                                                                   "(default: no limit)")
    ap.add_argument("--no-render", action="store_true", help="do not render diagram images")
    ap.add_argument("--cache-dir", type=Path, metavar="DIR",
                    help="directory of the LLM response store, llm.sqlite (default: OUT/.cache)")
    ap.add_argument("--llm-replay", type=Path, metavar="FILE",
                    help="answer LLM requests only from a recorded llm.sqlite, never the network; a request "
                         "with no recorded answer fails its project (for tests)")
    ap.add_argument("--force", action="store_true", help="allow writing into a non-empty output directory")
    ap.add_argument("--llm-concurrency", type=int, default=1, metavar="N",
                    help="LLM requests in flight at once (default 1; hosted endpoints usually allow more)")
    ap.add_argument("--heartbeat", type=float, default=30.0, metavar="SECONDS",
                    help="when stderr is not a terminal, log progress every SECONDS (default 30; 0: never); "
                         "on a terminal, progress bars are shown instead")
    ap.add_argument("--log-file", type=Path, metavar="FILE", help="also write a detailed (DEBUG) log to FILE")
    ap.add_argument("-v", "--verbose", action="count", default=0, help="-v: progress and phases; -vv: debug")
    ap.add_argument("--version", action="version", version=f"cameo-ingest {__version__}")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.log_file)

    if args.env is not None:
        if not args.env.is_file():
            print(f"error: --env file {args.env} not found", file=sys.stderr)
            return 2
        load_env(args.env)
    cfg = LLMConfig.from_env(args.text_model, args.vision_model, timeout=args.llm_timeout,
                             retries=args.llm_retries, max_calls=args.llm_max_calls)
    if args.no_llm:
        cfg.text_model = cfg.vision_model = None
    elif not cfg.enabled:  # fail fast rather than silently skip enrichment (BASE-020)
        print(NO_MODEL, file=sys.stderr)
        return 2

    out: Path = args.out
    if out.exists() and any(p.name != ".cache" for p in out.iterdir()) and not args.force:
        print(f"error: output directory {out} is not empty (use --force)", file=sys.stderr)
        return 2
    if args.llm_replay is not None and not (cfg.enabled and args.llm_replay.is_file()):
        print(f"error: --llm-replay needs a model and an existing store file ({args.llm_replay})", file=sys.stderr)
        return 2
    llm = LLM(cfg, args.cache_dir or out / ".cache", replay=args.llm_replay)
    if cfg.enabled and not args.no_preflight:
        log.info("checking LLM endpoint %s", cfg.base_url or "(OpenAI default)")
        err = llm.preflight()
        if err:
            print(f"error: LLM endpoint check failed ({cfg.base_url or 'OpenAI default endpoint'}): {err}\n"
                  "Check OPENAI_BASE_URL, OPENAI_API_KEY and the model name, or pass --no-preflight.",
                  file=sys.stderr)
            return 5
    out.mkdir(parents=True, exist_ok=True)

    data = args.source.read_bytes()
    source = SourceInfo(path=str(args.source), sha256=sha256_bytes(data), size=len(data),
                        metadata=_parse_meta(args.meta, args.meta_file))
    run = RunInfo(source=source, llm=cfg.public() if cfg.enabled else {})

    started = time.monotonic()
    try:
        projects = list(discover(data, args.source.name))
    except UnsupportedInput as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if not projects:
        print(f"error: no Cameo/XMI model found in {args.source}", file=sys.stderr)
        return 3
    log.info("found %d project(s) in %s in %.1f s", len(projects), source.name, time.monotonic() - started)
    progress = Progress(heartbeat=args.heartbeat)  # bars on a terminal, heartbeat lines otherwise

    # manifest.json depends only on the input, the options and the tool version, so two runs
    # can be compared file by file; run-specific facts go to run.json (BASE-015).
    manifest = {
        "tool": run.tool,
        "source": {"name": source.name, "sha256": source.sha256, "size": source.size, "metadata": source.metadata},
        "options": {"render": not args.no_render, "llm": run.llm},
        "projects": [], "failed": [], "files": [],
    }
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
            result = ingest_project(run, proj, out / name, llm, render=not args.no_render, progress=progress,
                                    concurrency=args.llm_concurrency)
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
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    record = {"run_id": run.run_id, "started": run.started, "finished": utc_now(), "tool": run.tool,
              "source_path": source.path, "argv": sys.argv[1:] if argv is None else list(argv),
              "llm": llm.report()}
    (out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(projects)} project(s), {len(all_chunks)} chunks, {len(manifest['files'])} files -> {out}")
    if manifest["failed"]:
        print(f"error: {len(manifest['failed'])} of {len(projects)} project(s) failed; see manifest.json",
              file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())

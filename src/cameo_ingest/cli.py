"""Command line: an output tree with a task list of inputs (plan RI-03).

    cameo-ingest add -o OUT PATH... [--meta K=V]   add inputs to the task list
    cameo-ingest run -o OUT [options]              process pending inputs and unfinished projects
    cameo-ingest ingest -o OUT PATH... [options]   add, then run (the default command)
    cameo-ingest status -o OUT [--json]            what the tree holds, and the latest run
    cameo-ingest prune -o OUT [--dry-run]          drop missing inputs and the projects only they held
    cameo-ingest export -o OUT --workbook FILE     the catalog, to search without tools (plan KX)
    cameo-ingest quality sample -o OUT [--n N]     draw a spot-check set of LLM requests and answers
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

from . import __version__
from . import runner as tree
from .archive import ZIP_MAGIC, sniff_xmi
from .config import ProjectOptions, TreeSettings, parse_modules
from .llm import EnrichmentSession, LLMConfig, connect
from .progress import Progress
from .runner import Runner
from .state import State, StateError

log = logging.getLogger("cameo_ingest")

COMMANDS = ("add", "run", "ingest", "status", "prune", "quality", "export")

NO_MODEL = """error: no LLM model is configured. Either
  - pass --no-llm to ingest without LLM summaries and descriptions, or
  - name a model with --text-model / --vision-model, or set CAMEO_INGEST_TEXT_MODEL
    (or OPENAI_MODEL) in the environment or in a file loaded with --env FILE.
The endpoint comes from OPENAI_BASE_URL and OPENAI_API_KEY; see .env.example.
An output tree remembers these choices, so later runs need no flags."""

# Run settings an output tree remembers (never secrets: --env names a file), from their flags;
# --no-llm and --render are read apart.
SETTINGS = tuple(f.name for f in fields(TreeSettings) if f.name not in ("no_llm", "render"))

PROGRESS_LOGGER = "cameo_ingest.progress"
_handlers: list[logging.Handler] = []  # ours, replaced when main() runs again (as in tests)


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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cameo-ingest",
        description="Convert Cameo/MagicDraw projects (.mdzip, .mdzipx, .mdxml, or bundles such as .rdzip "
                    "containing them) into provenance-tagged Markdown, CSV and JSON for RAG ingestion. Output "
                    "goes to an output tree with a task list of inputs; runs can be stopped and continued.",
        epilog="Without a command, `ingest` is assumed: `cameo-ingest FILE -o OUT`. "
               "Exit status: 0 success; 2 usage or configuration error; 3 an input had no readable model; "
               "4 some projects failed (the others are written); 5 the LLM endpoint check failed; "
               "130 interrupted (run again to continue).",
    )
    ap.add_argument("--version", action="version", version=f"cameo-ingest {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-o", "--out", type=Path,
                        help="output tree (created if missing; default: $CAMEO_INGEST_DEST)")
    common.add_argument("-v", "--verbose", action="count", default=0, help="-v: phases; -vv: debug")
    common.add_argument("--log-file", type=Path, metavar="FILE", help="also write a detailed (DEBUG) log to FILE")

    inputs = argparse.ArgumentParser(add_help=False)
    inputs.add_argument("paths", type=Path, nargs="+", metavar="PATH",
                        help="input files, or directories to search for them")
    inputs.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                        help="provenance metadata for these inputs (repeatable)")
    inputs.add_argument("--meta-file", action="append", default=[], metavar="JSON",
                        help="JSON object of provenance metadata (repeatable; --meta wins)")

    running = argparse.ArgumentParser(add_help=False)
    g = running.add_argument_group("run settings (remembered by the output tree)")
    g.add_argument("--env", type=Path, metavar="FILE",
                   help="load environment variables from a dotenv file (variables already set win)")
    g.add_argument("--text-model", help="LLM for summaries (overrides CAMEO_INGEST_TEXT_MODEL, OPENAI_MODEL)")
    g.add_argument("--vision-model", help="LLM for image descriptions (overrides CAMEO_INGEST_VISION_MODEL; "
                                          "default: the text model)")
    g.add_argument("--no-llm", action="store_true", help="no LLM enrichment (required when no model is configured)")
    flag_pair(g, "render", "render diagram sketches", "do not render sketches", default=True)
    g.add_argument("--image-pixels", type=int, metavar="N",
                   help="pixel budget of diagram sketches and of images sent to the vision model (default 645120: "
                        "gemma-4's 280 soft tokens of 48 x 48 px, all that DeepInfra gives it)")
    g.add_argument("--diagram-modules", metavar="N:MIN:MAX",
                   help="split diagrams of more than N shapes into modules of MIN to MAX shapes, each drawn and "
                        "described on its own (default 25:6:25; N = 0 never splits). For tuning: the default "
                        "should serve")
    flag_pair(g, "rag-files", "write rag/: every chunk as a .txt file, ending with its source and trace, for RAG "
              "tools that read files but not JSONL", "do not write rag/ (chunks.jsonl has the same chunks)",
              default=True)
    flag_pair(g, "cross-index", "index identifiers across every model in the tree: CROSSREF.md and index:id chunks",
              "no index across the models", default=True)
    flag_pair(g, "threads", "include each model's derivation trees of requirements, with what satisfies and "
              "verifies them, in the tree's chunks and rag/, as trace:thread chunks (each project's THREADS.md "
              "has them either way)", "leave the threads out of the tree's chunks", default=True)
    flag_pair(g, "line-refs", "end each line of an assembled chunk (an index entry, a thread) with a short reference "
              "to its source chunk, [project:chunk], not only to its project; the references lengthen entries, so "
              "fewer fit one window whole", "each line names only its project, by short id", default=False)
    g.add_argument("--rag-source", choices=("trace", "id"),
                   help="what the source line of every file in rag/ says: the project and trace locator (trace, the "
                        "default), or short ids that rag/meta/_sources.json and chunks.jsonl resolve to files and "
                        "locators (id). Set for the whole tree: a run rewrites rag/ in the new form, without "
                        "ingesting again")
    g.add_argument("--llm-timeout", type=float, metavar="SECONDS", help="per-request timeout (default 120)")
    g.add_argument("--llm-retries", type=int, metavar="N", help="retries per request (default 2)")
    g.add_argument("--llm-max-calls", type=int, metavar="N", help="stop calling the LLM after N requests in a run "
                                                                  "(default: no limit)")
    g.add_argument("--llm-concurrency", type=int, metavar="N",
                   help="LLM requests in flight at once (default 1; hosted endpoints usually allow more)")
    g.add_argument("--cache-dir", type=Path, metavar="DIR",
                   help="directory of the LLM response store, llm.sqlite (default: OUT/.cache)")
    r = running.add_argument_group("this run only")
    r.add_argument("--no-preflight", action="store_true",
                   help="skip the check that each LLM model answers before work starts")
    r.add_argument("--llm-replay", type=Path, metavar="FILE",
                   help="answer LLM requests only from a recorded llm.sqlite, never the network; a request "
                        "with no recorded answer fails its project (for tests)")
    r.add_argument("--heartbeat", type=float, default=30.0, metavar="SECONDS",
                   help="when stderr is not a terminal, log progress every SECONDS (default 30; 0: never); "
                        "on a terminal, progress bars are shown instead")

    sub = ap.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser("add", parents=[common, inputs], help="add inputs to the task list")
    sub.add_parser("run", parents=[common, running], help="process pending inputs and unfinished projects")
    sub.add_parser("ingest", parents=[common, inputs, running], help="add inputs, then run (the default)")
    st = sub.add_parser("status", parents=[common], help="what the tree holds, and the latest run")
    st.add_argument("--json", action="store_true", help="print JSON")
    pr = sub.add_parser("prune", parents=[common],
                        help="drop missing inputs, and the projects that no remaining input contains")
    pr.add_argument("--dry-run", action="store_true", help="only list what would be removed")
    ex = sub.add_parser("export", parents=[common],
                        help="write the catalog of the tree's models for people to search without tools: a "
                             "workbook (see README, Searching without tools)")
    ex.add_argument("--workbook", type=Path, metavar="FILE", required=True,
                    help="write the catalog as an Excel workbook (.xlsx) to FILE")
    q = sub.add_parser("quality", help="measure the quality of LLM enrichment (see docs/plans/llm-quality-*.md)")
    qs = q.add_subparsers(dest="action", required=True, metavar="ACTION")
    qsample = qs.add_parser("sample", parents=[common], help="draw a spot-check set of requests and answers")
    qsample.add_argument("--n", type=int, default=30, help="items to draw (default 30)")
    qsample.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    qsample.add_argument("--kind", action="append", metavar="KIND",
                         help="only this kind: diagram_description, module_description (of a large diagram), "
                              "image_description, summary, module_summary (part of a large package); repeatable")
    return ap


# Files of these types are never Cameo projects, and are skipped without being opened. Many are
# ZIP archives (Office and OpenDocument files, Java archives), which would otherwise be taken
# for candidates and read in full, only to fail.
NOT_MODELS = frozenset([".doc", ".docx", ".docm", ".dotx", ".xls", ".xlsx", ".xlsm", ".xltx", ".ppt", ".pptx", ".pptm", ".potx", ".vsd", ".vsdx", ".odt", ".ods", ".odp", ".odg", ".pdf", ".epub", ".rtf", ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".html", ".htm", ".msg", ".eml", ".log", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".ico", ".webp", ".mp3", ".wav", ".mp4", ".mov", ".avi", ".mkv", ".jar", ".war", ".ear", ".apk", ".whl", ".nupkg", ".msix", ".exe", ".dll", ".so", ".msi", ".iso", ".class", ".pyc"])


def _candidates(path: Path, out: Path, progress: Progress) -> list[Path]:
    """Files to add for PATH: the file itself, or the ZIP archives and XMI documents under a
    directory (the output tree, hidden directories and NOT_MODELS types excluded). The walk
    reports its progress: a directory on a network share can take minutes."""
    if path.is_file():
        return [path.resolve()]
    found: list[Path] = []
    out = out.resolve()
    skipped = unreadable = 0
    log.info("looking for models under %s", path)
    with progress.phase(f"looking for models under {path.name or path}", unit="file") as ph:
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                             and not Path(root, d).resolve().is_relative_to(out))
            for name in sorted(files):
                ph.advance()
                f = Path(root, name)
                if f.suffix.lower() in NOT_MODELS:
                    skipped += 1
                    continue
                try:
                    with f.open("rb") as fh:
                        head = fh.read(4096)
                except OSError as e:
                    unreadable += 1
                    log.warning("cannot read %s: %s", f, e)
                    continue
                if head.startswith(ZIP_MAGIC) or sniff_xmi(head):
                    log.debug("candidate: %s (%s)", f, "ZIP" if head.startswith(ZIP_MAGIC) else "XMI")
                    found.append(f.resolve())
                    if len(found) % 50 == 0:
                        log.info("found %d candidate(s) in %d file(s) so far", len(found), ph.done)
            log.debug("searched %s", root)
    log.info("found %d candidate(s) under %s; %d file(s) skipped by type, %d unreadable",
             len(found), path, skipped, unreadable)
    return sorted(found)


def add_inputs(state: State, args: argparse.Namespace) -> tuple[int, int]:
    """Add the command line's paths to the task list: (new inputs, inputs already listed)."""
    meta = _parse_meta(args.meta, args.meta_file)
    missing = [p for p in args.paths if not p.exists()]
    if missing:
        raise SystemExit(f"error: no such file or directory: {', '.join(map(str, missing))}")
    new = old = 0
    beat = getattr(args, "heartbeat", 10.0)  # the walk reports at least every 10 s, unless told not to
    progress = Progress(heartbeat=min(beat, 10.0) if beat else 0)
    for path in args.paths:
        for f in _candidates(path, args.out, progress):
            if state.add_input(f, meta):
                new += 1
            else:
                old += 1
    log.info("added %d input(s) to the task list (%d already listed)", new, old)
    return new, old


def export_catalog(out: Path, args: argparse.Namespace) -> int:
    """`export`: the tree's catalogs as a workbook (plan KX-06)."""
    from . import catalog, workbook

    state = State(out)
    missing: list[str] = []
    try:
        rows = workbook.write_workbook(args.workbook, catalog.tree_catalogs(state, out, missing, Progress()),
                                       __version__)
    finally:
        state.close()
    size = args.workbook.stat().st_size
    print(f"wrote {args.workbook} ({size / 1e6:.1f} MB): " + ", ".join(f"{n:,} {k}" for k, n in rows.items()))
    if missing:
        print(f"note: {len(missing)} project(s) were made before catalogs existed and are left out: "
              f"{', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}; `run` makes them again", file=sys.stderr)
    return 0


def flag_pair(group: Any, name: str, on: str, off: str, default: bool) -> None:
    """--NAME and --no-NAME, both setting NAME (None when neither is given: the stored setting,
    or `default`), with the default named in the help (AR-013R2)."""
    dest = name.replace("-", "_")
    group.add_argument(f"--{name}", dest=dest, action="store_const", const=True, default=None,
                       help=on + (" (the default)" if default else ""))
    group.add_argument(f"--no-{name}", dest=dest, action="store_const", const=False,
                       help=off + ("" if default else " (the default)"))


def effective_settings(args: argparse.Namespace, stored: dict[str, Any]) -> TreeSettings:
    """The tree's stored settings, overridden by the flags given on this command line."""
    s = dict(stored)
    if s.pop("chunk_style", None) == "markdown":  # retired in 0.6.0 (plan RA-02)
        log.warning("the Markdown chunk style is retired: this tree's chunks will be plain text")
    for key in SETTINGS:
        v = getattr(args, key, None)
        if v is not None:
            s[key] = str(v.resolve()) if isinstance(v, Path) else v
    if args.text_model or args.vision_model:
        s["no_llm"] = False
    if args.no_llm:
        s["no_llm"] = True
    if args.render is not None:
        s["render"] = args.render
    return TreeSettings.from_stored(s)


def run_tree(args: argparse.Namespace, argv: list[str]) -> int:
    out: Path = args.out
    stored: dict[str, Any] = {}
    if State.exists(out):
        st = State(out)
        stored = st.settings()
        st.close()
    settings = effective_settings(args, stored)
    if settings.env:
        env = Path(settings.env)
        if not env.is_file():
            print(f"error: --env file {env} not found", file=sys.stderr)
            return 2
        load_env(env)
    try:
        parse_modules(settings.diagram_modules)  # a malformed --diagram-modules stops here
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cfg = LLMConfig.from_env(settings.text_model, settings.vision_model, timeout=settings.llm_timeout,
                             retries=settings.llm_retries, max_calls=settings.llm_max_calls)
    if settings.no_llm:
        cfg.text_model = cfg.vision_model = None
    elif not cfg.enabled:  # fail fast rather than silently skip enrichment (BASE-020)
        print(NO_MODEL, file=sys.stderr)
        return 2
    if args.llm_replay is not None and not (cfg.enabled and args.llm_replay.is_file()):
        print(f"error: --llm-replay needs a model and an existing store file ({args.llm_replay})", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, Path(settings.cache_dir) if settings.cache_dir else out / ".cache",
                            connect(cfg, args.llm_replay))
    if cfg.enabled and not args.no_preflight:
        log.info("checking LLM endpoint %s", cfg.base_url or "(OpenAI default)")
        err = llm.preflight()
        if err:
            print(f"error: LLM endpoint check failed ({cfg.base_url or 'OpenAI default endpoint'}): {err}\n"
                  "Check OPENAI_BASE_URL, OPENAI_API_KEY and the model name, or pass --no-preflight.",
                  file=sys.stderr)
            return 5

    state = State(out)
    try:
        state.lock()
        if args.command == "ingest":
            add_inputs(state, args)
        state.save_settings(settings.stored())
        options = ProjectOptions.of(settings, cfg.text_model, cfg.vision_model, cfg.max_calls)
        runner = Runner(state, out, llm, options, Progress(heartbeat=args.heartbeat),
                        concurrency=settings.llm_concurrency or 1)
        previous = signal.signal(signal.SIGTERM, _interrupt)
        try:
            code = runner.run(argv)
        except KeyboardInterrupt:
            print(f"interrupted; finished work is kept. Continue with: cameo-ingest run -o {out}", file=sys.stderr)
            return 130
        finally:
            signal.signal(signal.SIGTERM, previous)
        counts = state.counts("projects")
        print(f"{len(runner.written)} project(s) written in this run; in {out}: "
              + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
        return code
    except StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        state.close()


def _interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt  # SIGTERM stops a run the same way as Ctrl-C


def print_status(state: State, as_json: bool) -> None:
    s = tree.status(state)
    if as_json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return
    def counts(c: dict[str, int]) -> str:
        return ", ".join(f"{n} {k}" for k, n in sorted(c.items())) or "none"
    print(f"inputs: {counts(s['inputs']['counts'])}")
    for p in s["inputs"]["problems"]:
        print(f"  {p['status']}: {p['path']}" + (f" ({p['error']})" if p["error"] else ""))
    print(f"projects: {counts(s['projects']['counts'])}")
    for p in s["projects"]["failed"]:
        print(f"  failed: {p['name']} {p['token'][:23]} ({p['error']})")
    run = s["latest_run"]
    if run:
        print(f"latest run: {run['outcome'] or 'running or stopped'}, started {run['started']}"
              + (f", {run['llm_calls']} LLM calls" if run["llm_calls"] is not None else ""))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not {"-h", "--help", "--version"} & set(argv):
        argv.insert(0, "ingest")  # `cameo-ingest FILE -o OUT` keeps working
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.log_file)
    if args.out is None:  # the tree from the environment, or from an --env file given here
        if getattr(args, "env", None) and args.env.is_file() and "CAMEO_INGEST_DEST" not in os.environ:
            load_env(args.env)
        if not os.environ.get("CAMEO_INGEST_DEST"):
            print("error: no output tree: give -o DIR, or set CAMEO_INGEST_DEST", file=sys.stderr)
            return 2
        args.out = Path(os.environ["CAMEO_INGEST_DEST"])
    out: Path = args.out
    if not State.exists(out):
        if args.command in ("run", "status", "prune", "quality", "export"):
            print(f"error: no output tree at {out}; start one with `add` or `ingest`", file=sys.stderr)
            return 2
        if out.exists() and any(p.name != ".cache" for p in out.iterdir()):
            print(f"error: {out} is not empty and is not a cameo-ingest output tree (no state.sqlite)",
                  file=sys.stderr)
            return 2
    if args.command == "add":
        state = State(out)
        try:
            new, old = add_inputs(state, args)
        finally:
            state.close()
        print(f"added {new} input(s) to the task list of {out} ({old} already listed); `run` processes them")
        return 0
    if args.command == "status":
        state = State(out)
        try:
            print_status(state, args.json)
        finally:
            state.close()
        return 0
    if args.command == "quality":
        from . import quality

        state = State(out)
        cache = Path(TreeSettings.from_stored(state.settings()).cache_dir or out / ".cache")
        state.close()
        try:
            set_dir = quality.sample(out, cache, n=args.n, seed=args.seed, kinds=args.kind)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        meta = json.loads((set_dir / "set.json").read_text())
        print(f"spot-check set {set_dir}: {meta['items']} of {meta['available']} items, {len(meta['templates'])} "
              f"templates; open {set_dir / 'index.html'}")
        if meta["unexplained"]:
            print(f"note: {meta['unexplained']} generated chunks predate the request log and were left out; "
                  "a run with the same settings logs them without new LLM calls", file=sys.stderr)
        return 0
    if args.command == "export":
        return export_catalog(out, args)
    if args.command == "prune":
        state = State(out)
        try:
            state.lock()
            removed = tree.prune(state, out, dry_run=args.dry_run)
        except StateError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        finally:
            state.close()
        verb = "would remove" if args.dry_run else "removed"
        print(f"{verb} {len(removed['inputs'])} missing input(s) and {len(removed['projects'])} project(s)")
        for p in removed["projects"]:
            print(f"  {p['name']} {p['token'][:23]}")
        return 0
    return run_tree(args, argv)


if __name__ == "__main__":
    sys.exit(main())

"""Command line: an output tree with a task list of inputs (plan RI-03).

    cameo-ingest add -o OUT PATH... [--meta K=V]   add inputs to the task list
    cameo-ingest run -o OUT [options]              process pending inputs and unfinished projects
    cameo-ingest ingest -o OUT PATH... [options]   add, then run (the default command)
    cameo-ingest status -o OUT [--json]            what the tree holds, and the latest run
    cameo-ingest prune -o OUT [--dry-run]          drop missing inputs and the projects only they held
    cameo-ingest export -o OUT [--workbook F] [--search-page F]   the catalog, to search without tools
    cameo-ingest scan -o OUT                       find the projects in the inputs, building nothing
    cameo-ingest projects -o OUT [--csv FILE]      every project: status, save time, size, where found
    cameo-ingest groups -o OUT [--csv FILE]        versions of the same model, by shared element ids
    cameo-ingest remove -o OUT TOKEN... [--dry-run]   remove projects from the tree, and keep them out
    cameo-ingest restore -o OUT TOKEN...           undo `remove`; the next run builds them again
    cameo-ingest quality sample -o OUT [--n N]     draw a spot-check set of LLM requests and answers
    cameo-ingest calibrate-vision -o OUT [--suite S]   eye charts: the sketch settings for the vision model
    cameo-ingest calibrate-text -o OUT             reading cards: the part size for the text model (a guard)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

from . import __version__
from . import runner as tree
from .archive import ZIP_MAGIC, sniff_xmi
from .config import IMAGE_PIXELS, ProjectOptions, TreeSettings
from .llm import EnrichmentSession, LLMConfig, connect
from .progress import Progress
from .runner import Runner
from .state import State, StateError

log = logging.getLogger("cameo_ingest")
DEFAULT_TREE = "ingest_tree"  # in the working directory, when neither -o nor $CAMEO_INGEST_TREE says (plan CF)

COMMANDS = ("add", "run", "ingest", "status", "prune", "quality", "export", "scan", "projects", "groups", "remove",
            "restore", "calibrate-vision", "calibrate-text", "config")

NO_MODEL = """error: the tree uses the LLM, but names no model. Either
  - cameo-ingest config set text-model NAME (and vision-model, if another model reads images), or
  - cameo-ingest config set llm off, to ingest without summaries and descriptions,
or set it all up with `cameo-ingest config -i`. The endpoint is $OPENAI_BASE_URL (unset: OpenAI),
its key $OPENAI_API_KEY; `cameo-ingest config models` lists the endpoint's models."""

# Settings a tree may remember from an older version, now fixed defaults or calibrated
# (ADR-0027, 2026-10-05; plan CF, 0.21.0): ignored, with a notice.
RETIRED = ("cross_index", "threads", "hierarchies", "line_refs", "env", "llm_timeout", "llm_retries", "cache_dir",
           "image_pixels", "diagram_modules", "sketch_font_px", "sketch_arrow_px", "sketch_line_px", "image_first",
           "part_chars", "calibrate")

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
                        help=f"output tree (created if missing; default: $CAMEO_INGEST_TREE, else ./{DEFAULT_TREE})")
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
    # For tests and developers, not users: hidden from help. The tree's settings are `config`'s (plan CF).
    running.add_argument("--no-preflight", action="store_true", help=argparse.SUPPRESS)
    running.add_argument("--no-calibrate", action="store_true", help=argparse.SUPPRESS)
    running.add_argument("--llm-replay", type=Path, metavar="FILE", help=argparse.SUPPRESS)
    running.add_argument("--heartbeat", type=float, default=30.0, metavar="SECONDS", help=argparse.SUPPRESS)

    sub = ap.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser("add", parents=[common, inputs], help="add inputs to the task list")
    sub.add_parser("run", parents=[common, running], help="process pending inputs and unfinished projects")
    sub.add_parser("ingest", parents=[common, inputs, running], help="add inputs, then run (the default)")
    cf = sub.add_parser("config", parents=[common], help="show or change the tree's settings (plan CF)",
                        description="The tree's settings: show them, set one, or unset one (back to its default); "
                                    "or -i, asked for one by one and tested. The LLM endpoint and key are "
                                    "$OPENAI_BASE_URL and $OPENAI_API_KEY.")
    cf.add_argument("-i", "--interactive", action="store_true",
                    help="ask for each setting, list and test the endpoint's models, and save at the end")
    cfs = cf.add_subparsers(dest="action", metavar="ACTION")
    cfs.add_parser("show", help="each setting, its value, and whether it is the tree's own or the default")
    cset = cfs.add_parser("set", help="set a setting")
    cset.add_argument("key", metavar="KEY")
    cset.add_argument("value", metavar="VALUE")
    cunset = cfs.add_parser("unset", help="return a setting to its default")
    cunset.add_argument("key", metavar="KEY")
    cfs.add_parser("test", help="check the endpoint and key, and that each model answers (the vision model reads an "
                                "image); exits 5 when a check fails")
    cmodels = cfs.add_parser("models", help="the endpoint's models, those the tree uses or has calibrated marked")
    cmodels.add_argument("filter", nargs="?", metavar="TEXT", help="only models whose id holds TEXT")
    st = sub.add_parser("status", parents=[common], help="what the tree holds, and the latest run")
    st.add_argument("--json", action="store_true", help="print JSON")
    pr = sub.add_parser("prune", parents=[common],
                        help="drop missing inputs, and the projects that no remaining input contains")
    pr.add_argument("--dry-run", action="store_true", help="only list what would be removed")
    ex = sub.add_parser("export", parents=[common],
                        help="write the catalog of the tree's models for people to search without tools: a "
                             "workbook, a search page (see README, Searching without tools)")
    ex.add_argument("--workbook", type=Path, metavar="FILE", help="write the catalog as an Excel workbook (.xlsx)")
    ex.add_argument("--search-page", type=Path, metavar="FILE",
                    help="write the catalog as one self-contained web page (.html) that searches in a browser")
    ex.add_argument("--sketches", choices=("none", "webp", "svg"), default="none",
                    help="put the diagrams' sketches in the search page: the PNG sketches as WebP, or the SVG "
                         "sketches (default: none)")
    sub.add_parser("scan", parents=[common],
                   help="find the projects in the task list's inputs, and what each says about itself (its save time "
                        "and element ids), building nothing; then `projects` and `groups` can show them")
    pj = sub.add_parser("projects", parents=[common],
                        help="every project in the tree: status, save time, Cameo version, size, where it was found")
    pj.add_argument("--csv", type=Path, metavar="FILE", help="also write the list as CSV")
    gr = sub.add_parser("groups", parents=[common],
                        help="versions of the same model, found by the element ids they share, newest first")
    gr.add_argument("--csv", type=Path, metavar="FILE", help="also write the groups as CSV")
    gr.add_argument("--include-removed", action="store_true", help="compare removed projects too")
    rm = sub.add_parser("remove", parents=[common],
                        help="remove projects from the tree, and keep them out of later runs while their inputs "
                             "remain (their LLM answers stay cached)")
    rm.add_argument("tokens", nargs="+", metavar="TOKEN",
                    help="a project's sha256 (sha256:... or its first 8 or more hex digits)")
    rm.add_argument("--dry-run", action="store_true", help="only list what would be removed")
    rs = sub.add_parser("restore", parents=[common], help="undo `remove`: the next run builds the projects again")
    rs.add_argument("tokens", nargs="+", metavar="TOKEN", help="as for remove")
    about = ("calibrate the sketches to the tree's vision model, as the first run with a model does on its own: "
             "eye charts drawn as sketches are, read by the model, and the sizes they call for (see README, "
             "Calibrating sketches to the vision model). The standard suite's calibration is recorded in the tree, "
             "and runs with that model use it")
    cv = sub.add_parser("calibrate-vision", parents=[common, running], help=about, description=about)
    c = cv.add_argument_group("calibration")
    c.add_argument("--suite", choices=("quick", "standard"), default="standard",
                   help="quick: 11 eye charts, to check a model; standard: 80, and a trial of the image's place, to "
                        "calibrate it (the default)")
    about = ("calibrate the part size to the tree's text model, as the first run with a model does on its own: "
             "reading cards of 6,000 to 24,000 characters, 30 requests (see README, Calibrating the part size to the "
             "text model). It only lowers the part size, for a model that reads 12,000 characters unevenly. The "
             "calibration is recorded in the tree, and runs with that model use it")
    sub.add_parser("calibrate-text", parents=[common, running], help=about, description=about)
    q = sub.add_parser("quality", help="measure the quality of LLM enrichment (see docs/design/llm-enrichment.md)")
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
    """`export`: the tree's catalogs as a workbook and a search page (plan KX-06)."""
    from . import catalog, searchpage, workbook

    if not (args.workbook or args.search_page):
        print("error: export needs --workbook FILE, --search-page FILE or both", file=sys.stderr)
        return 2
    state = State(out)
    missing: list[str] = []
    try:
        from . import lineage, subjects
        from .provenance import ContentInfo

        sub = out / subjects.FILE
        families = json.loads(sub.read_text(encoding="utf-8")) if sub.is_file() else None
        facts = lineage.facts(state)  # each model's save time, version, family and kin (plan LN-06)
        for r in state.written():
            if f"sha256:{r['content_sha256']}" in facts:
                facts[f"sha256:{r['content_sha256']}"]["label"] = ContentInfo(r["content_sha256"], r["name"]).label
        if args.workbook:
            rows = workbook.write_workbook(args.workbook, catalog.tree_catalogs(state, out, missing, Progress()),
                                           __version__, families, facts)
            print(f"wrote {args.workbook} ({args.workbook.stat().st_size / 1e6:.1f} MB): "
                  + ", ".join(f"{n:,} {k}" for k, n in rows.items()))
        if args.search_page:
            missing.clear()
            counts = searchpage.write_search_page(
                args.search_page, catalog.tree_catalogs(state, out, missing, Progress(), chunks=True), __version__,
                args.sketches, families, facts)
            print(f"wrote {args.search_page} ({args.search_page.stat().st_size / 1e6:.1f} MB): "
                  f"{counts['items']:,} items from {counts['projects']:,} models"
                  + (f", {counts['sketches']:,} sketches ({counts['sketch bytes'] / 1e6:.1f} MB)"
                     if counts["sketches"] else ""))
    finally:
        state.close()
    if missing:
        print(f"note: {len(missing)} project(s) were made before catalogs existed and are left out: "
              f"{', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}; `run` makes them again", file=sys.stderr)
    return 0


def _paths(state: State) -> dict[str, list[str]]:
    """Each content's places: input path, then archive members, '!' between."""
    out: dict[str, list[str]] = {}
    for r in state.catalog():
        out[r["sha256"]] = list(dict.fromkeys("!".join([s["path"], *json.loads(s["chain"])])
                                              for s in state.sightings(r["sha256"])))
    return out


def _resolve(tokens: list[str], candidates: dict[str, str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Tokens (sha256:..., or 8 or more hex digits) to (sha256, name) among `candidates`; and errors."""
    found, errors = [], []
    for t in tokens:
        hexes = t.removeprefix("sha256:").lower()
        if len(hexes) < 8 or any(c not in "0123456789abcdef" for c in hexes):
            errors.append(f"{t}: give sha256:... or at least 8 hex digits")
            continue
        hits = [(sha, name) for sha, name in candidates.items() if sha.startswith(hexes)]
        if len(hits) != 1:
            errors.append(f"{t}: {'no project' if not hits else f'{len(hits)} projects'} match")
            continue
        found.append(hits[0])
    return found, errors


def versions_command(out: Path, args: argparse.Namespace) -> int:
    """`scan`, `projects`, `groups`, `remove` and `restore` (plan PV)."""
    import csv

    from . import groups as gp

    state = State(out)
    try:
        if args.command == "scan":
            state.lock()
            cfg = LLMConfig(None, None, None)
            runner = Runner(state, out, EnrichmentSession(cfg, out / ".cache", None), ProjectOptions(),
                            Progress(heartbeat=10))
            runner.check_inputs()
            runner.scan()
            caught_up = runner.fingerprint_missing()
            counts = state.counts("projects")
            print(f"scanned {out}: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
                  + (f"; {caught_up} fingerprinted from earlier scans" if caught_up else "")
                  + f". See `cameo-ingest projects -o {out}` and `cameo-ingest groups -o {out}`")
            return 3 if runner.failed_inputs else 0
        if args.command == "projects":
            rows, paths = state.catalog(), _paths(state)
            for r in rows:
                where = paths.get(r["sha256"], [])
                print(f"{r['sha256'][:8]}  {r['status']:<8} {(r['saved_raw'] or '-'):<30} {(r['exporter'] or '-'):<24} "
                      f"{(r['elements'] or 0):>8,}  {r['name']}  ({len(where)} place{'s' if len(where) != 1 else ''})")
            print(f"{len(rows)} project(s); `groups` finds versions of the same model")
            if args.csv:
                with args.csv.open("w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["token", "name", "status", "saved", "saved_from", "exporter", "project_id",
                                "elements", "paths"])
                    for r in rows:
                        w.writerow([f"sha256:{r['sha256']}", r["name"], r["status"], r["saved_raw"] or "",
                                    r["saved_from"] or "", r["exporter"] or "", r["project_id"] or "",
                                    r["elements"] or "", "; ".join(paths.get(r["sha256"], []))])
            return 0
        if args.command == "groups":
            from . import lineage

            report = gp.find(state.catalog(), state.fingerprint_ids(), _paths(state), args.include_removed,
                             lineage.pairs(state, args.include_removed))
            print(gp.render(report, out))
            if args.csv:
                gp.write_csv(report, args.csv)
            return 0
        if args.command == "remove":
            items, errors = _resolve(args.tokens, {r["sha256"]: r["name"] for r in state.catalog()
                                                   if r["status"] != "removed"})
            for e in errors:
                print(f"error: {e}", file=sys.stderr)
            if errors:
                return 2
            for sha, name in items:
                print(f"{'would remove' if args.dry_run else 'removing'} {name} sha256:{sha[:16]}")
            if args.dry_run:
                return 0
            state.lock()
            state.remove(items)
            for sha, _ in items:
                for d in (out / tree.exports.PROJECTS / sha, out / tree.exports.PROJECTS / tree.WORK / sha):
                    if d.exists():
                        shutil.rmtree(d)
            tree.exports.rebuild(state, out)
            print(f"removed {len(items)} project(s); later runs leave them out. `restore` undoes this")
            return 0
        items, errors = _resolve(args.tokens, {r["content_sha256"]: r["name"] for r in state.removed()})
        for e in errors:
            print(f"error: {e} (among removed projects)", file=sys.stderr)
        if errors:
            return 2
        state.lock()
        state.restore([sha for sha, _ in items])
        print(f"restored {len(items)} project(s); the next `run` builds them again, reusing their LLM answers")
        return 0
    except StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        state.close()


def flag_pair(group: Any, name: str, on: str, off: str, default: bool) -> None:
    """--NAME and --no-NAME, both setting NAME (None when neither is given: the stored setting,
    or `default`), with the default named in the help (AR-013R2)."""
    dest = name.replace("-", "_")
    group.add_argument(f"--{name}", dest=dest, action="store_const", const=True, default=None,
                       help=on + (" (the default)" if default else ""))
    group.add_argument(f"--no-{name}", dest=dest, action="store_const", const=False,
                       help=off + ("" if default else " (the default)"))


def tree_settings(stored: dict[str, Any], quiet: bool = False) -> TreeSettings:
    """The tree's settings, as `config` set them (plan CF); those an older version remembered and
    that are now defaults or calibrated are left out, with a notice."""
    s = dict(stored)
    if s.pop("chunk_style", None) == "markdown" and not quiet:  # retired in 0.6.0 (plan RA-02)
        log.warning("the Markdown chunk style is retired: this tree's chunks will be plain text")
    retired = [k for k in RETIRED if s.pop(k, None) is not None]
    if retired and not quiet:  # heuristics are defaults, not settings (ADR-0027); the rest is `config`'s
        log.warning("this tree remembers settings that are now defaults or calibrated, and ignores them: %s",
                    ", ".join(sorted(retired)))
    return TreeSettings.from_stored(s)


def stored_settings(out: Path) -> dict[str, Any]:
    if not State.exists(out):
        return {}
    st = State(out)
    try:
        return st.settings()
    finally:
        st.close()


def llm_config(settings: TreeSettings) -> LLMConfig:
    """The tree's models and call budget, at $OPENAI_BASE_URL (plan CF)."""
    return LLMConfig.from_env(settings.text_model, settings.vision_model, max_calls=settings.llm_max_calls)


def check_endpoint(llm: EnrichmentSession) -> bool:
    """The endpoint answers each model; False, with the error printed, when it doesn't."""
    cfg = llm.cfg
    log.info("checking LLM endpoint %s", cfg.base_url or "(OpenAI default)")
    err = llm.preflight()
    if err:
        print(f"error: LLM endpoint check failed ({cfg.base_url or 'OpenAI default endpoint'}): {err}\n"
              "Check OPENAI_BASE_URL and OPENAI_API_KEY, and the model's name (`cameo-ingest config test`).",
              file=sys.stderr)
    return not err


def run_tree(args: argparse.Namespace, argv: list[str]) -> int:
    out: Path = args.out
    settings = tree_settings(stored_settings(out))
    cfg = llm_config(settings)
    if settings.no_llm:
        cfg.text_model = cfg.vision_model = None
    elif not cfg.enabled:  # fail fast rather than silently skip enrichment (BASE-020)
        print(NO_MODEL, file=sys.stderr)
        return 2
    if args.llm_replay is not None and not (cfg.enabled and args.llm_replay.is_file()):
        print(f"error: --llm-replay needs a model and an existing store file ({args.llm_replay})", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, shared_store(out, settings),
                            connect(cfg, args.llm_replay))
    if cfg.enabled and not args.no_preflight and not check_endpoint(llm):
        return 5

    state = State(out)
    try:
        state.lock()
        if args.command == "ingest":
            add_inputs(state, args)
        state.save_settings(settings.stored())  # without retired settings, once noticed
        progress = Progress(heartbeat=args.heartbeat)

        def prepare() -> ProjectOptions:  # after the scan: the models calibrated, if they aren't yet
            options = ProjectOptions.of(settings, cfg.text_model, cfg.vision_model, cfg.max_calls,
                                        calibration_for_run(out, state, llm, settings, progress,
                                                            calibrate=not args.no_calibrate))
            llm.image_first = options.image_first
            return options

        runner = Runner(state, out, llm, ProjectOptions.of(settings, cfg.text_model, cfg.vision_model, cfg.max_calls),
                        progress, concurrency=settings.llm_concurrency or 1, prepare=prepare)
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


def calibration_for_run(out: Path, state: State, llm: EnrichmentSession, settings: TreeSettings,
                        progress: Progress, calibrate: bool = True) -> dict[str, Any] | None:
    """The models' calibrations for a run, as settings: the text model's (plan TC), then the
    vision model's (plan VA). None: the uncalibrated defaults (`calibrate` off is for tests)."""
    if not calibrate:
        return None
    found = {**(text_calibration_for_run(out, state, llm, settings, progress) or {}),
             **(vision_calibration_for_run(out, state, llm, settings, progress) or {})}
    return found or None


def text_calibration_for_run(out: Path, state: State, llm: EnrichmentSession, settings: TreeSettings,
                             progress: Progress) -> dict[str, Any] | None:
    """The text model's calibration (plan TC-08): the tree's record, made first when it has none.
    It only guards: a model that reads 12,000 characters unevenly gets smaller parts."""
    from . import textcal

    cfg = llm.cfg
    if not cfg.text_model:
        return None
    found = textcal.recorded(state, cfg.base_url or "", cfg.text_model)
    if found is not None:
        return found
    n = 2 * textcal.GUARD_CARDS * len(textcal.GUARD_LENGTHS)
    print(f"calibrating to {cfg.text_model}, which this tree has no text calibration for: {n} requests of 6,000 to "
          "24,000 characters; the answers are stored, so this happens once per model and endpoint",
          file=sys.stderr)
    result = textcal.calibrate_text(out, state, llm, settings.llm_concurrency or 1, progress)
    if result.problem or result.settings is None:
        log.warning("the text calibration of %s is incomplete (%s): this run uses the default part size; see %s",
                    cfg.text_model, result.problem, result.dest / "report.md")
        return None
    if result.warning:
        log.warning("%s", result.warning)
    print(f"calibrated to {cfg.text_model}: part_chars {result.part_chars:,}, since it {result.why} (see "
          f"{result.dest / 'report.md'})", file=sys.stderr)
    return result.settings


def vision_calibration_for_run(out: Path, state: State, llm: EnrichmentSession, settings: TreeSettings,
                               progress: Progress) -> dict[str, Any] | None:
    """The vision model's calibration for a run (plan VA): the tree's record, made first when it
    has none and sketches are drawn. None: the uncalibrated defaults."""
    from . import calibrate

    cfg = llm.cfg
    if not cfg.vision_model:
        return None
    row = state.calibration(cfg.base_url or "", cfg.vision_model, calibrate.SUITE_VERSION)
    if row is not None:
        found, report_dir = json.loads(row["settings"]), out / row["report"]
        if row["validation"] is not None or not settings.render:
            return found
    elif not settings.render:
        return None
    else:
        print(f"calibrating the sketches to {cfg.vision_model}, which this tree has no calibration for: about 90 eye "
              "charts, a few minutes on a hosted model; the answers are stored, so this happens once per model "
              "and endpoint", file=sys.stderr)
        result = calibrate.calibrate_model(out, state, llm, "standard", settings.image_pixels or IMAGE_PIXELS,
                                           settings, settings.llm_concurrency or 1, progress, settings.image_first)
        if result.problem or result.settings is None:
            log.warning("the calibration of %s is incomplete (%s): this run draws to the uncalibrated defaults; "
                        "see %s", cfg.vision_model, result.problem, result.dest / "report.md")
            return None
        print(f"calibrated to {cfg.vision_model}: " + ", ".join(f"{k} {v}" for k, v in result.settings.items())
              + f" (the tree's own settings win; see {result.dest / 'report.md'})", file=sys.stderr)
        found, report_dir = result.settings, result.dest
    report_validation(state, llm, settings.calibrated(found), report_dir, settings.llm_concurrency or 1, progress)
    return found


def report_validation(state: State, llm: EnrichmentSession, sizes: TreeSettings, report_dir: Path,
                      concurrency: int, progress: Progress) -> None:
    """The calibration validated on the tree's own sketches (plan VA-05): a line, and warnings."""
    from . import validate

    summary = validate.validate(state, llm, sizes, report_dir, concurrency, progress)
    print(f"expected quality with {llm.cfg.vision_model}: {validate.one_line(summary)}"
          + (f" (see {report_dir / 'validation.md'})" if summary["overall"]["sketches"] else ""), file=sys.stderr)
    for w in summary["warnings"]:
        log.warning("%s", w)


def _sizes(t: TreeSettings) -> tuple[Any, ...]:
    return t.image_pixels or IMAGE_PIXELS, t.modules, t.sketch


def calibrate_text(out: Path, args: argparse.Namespace) -> int:
    """`calibrate-text` (plan TC): reading cards read by the tree's text model, and the part size
    they call for, recorded for runs with that model."""
    from . import textcal

    stored = stored_settings(out)
    settings = tree_settings(stored)
    cfg = llm_config(settings)
    cfg.vision_model = None  # text only
    if settings.no_llm or not cfg.text_model:
        print("error: calibrate-text needs a text model: cameo-ingest config set text-model NAME", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, shared_store(out, settings),
                            connect(cfg, args.llm_replay))
    if not args.no_preflight and not check_endpoint(llm):
        return 5
    state = State(out)
    try:
        state.lock()
        result = textcal.calibrate_text(out, state, llm, settings.llm_concurrency or 1,
                                        Progress(heartbeat=args.heartbeat))
    except KeyboardInterrupt:
        print("interrupted; the answers so far are stored, so running again asks only for the rest", file=sys.stderr)
        return 130
    except StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        state.close()
    print(f"part_chars: {result.part_chars:,}: the model {result.why}")
    print(f"the measurements are in {result.dest / 'report.md'}")
    if result.problem:
        print(f"warning: {result.problem}; see the replies in {result.dest / 'results.json'}. Not recorded",
              file=sys.stderr)
        return 2
    if result.warning:
        print(f"warning: {result.warning}", file=sys.stderr)
    print(f"recorded: runs with {cfg.text_model} use this part size")
    return 0


def calibrate_vision(out: Path, args: argparse.Namespace) -> int:
    """`calibrate-vision` (plans VC, VA): eye charts read by the tree's vision model, the sketch
    settings they call for, and the standard suite's calibration recorded for runs with that model."""
    from . import calibrate

    stored = stored_settings(out)
    settings = tree_settings(stored)
    cfg = llm_config(settings)
    cfg.text_model = None  # images only
    if settings.no_llm or not cfg.vision_model:
        print("error: calibrate-vision needs a vision model: cameo-ingest config set vision-model NAME (or "
              "text-model, which reads images too unless another is set)", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, shared_store(out, settings),
                            connect(cfg, args.llm_replay))
    if not args.no_preflight and not check_endpoint(llm):
        return 5
    state = State(out)
    try:
        state.lock()
        using = settings.calibrated(calibrate.recorded(state, cfg))
        try:
            result = calibrate.calibrate_model(out, state, llm, args.suite, settings.image_pixels or IMAGE_PIXELS,
                                               using, settings.llm_concurrency or 1, Progress(heartbeat=args.heartbeat),
                                               settings.image_first)
        except KeyboardInterrupt:
            print("interrupted; the answers so far are stored, so running again asks only for the rest",
                  file=sys.stderr)
            return 130
    except StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        state.close()
    for r in result.recs:
        print(f"{r.setting}: {r.recommended}" + (f" (was {r.current})" if r.changes else "") + f": {r.why}")
    print(f"the measurements are in {result.dest / 'report.md'}")
    if result.problem:
        print(f"warning: {result.problem}; see the replies in {result.dest / 'results.json'}. Not recorded",
              file=sys.stderr)
        return 2
    if result.settings is None:
        print("the quick suite checks a model and is not recorded; runs use the standard suite's calibration")
        return 0
    print(f"recorded: runs with {cfg.vision_model} use these settings")
    state = State(out)
    try:
        state.lock()
        report_validation(state, llm, settings.calibrated(result.settings), result.dest, settings.llm_concurrency or 1,
                          Progress(heartbeat=args.heartbeat))
    except StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        state.close()
    if _sizes(settings.calibrated(result.settings)) != _sizes(using):
        sketches = sum(1 for _ in (out / tree.exports.PROJECTS).glob("*/diagrams/**/*.png"))
        print(f"the next run with {cfg.vision_model} draws the tree's {sketches:,} sketches again and asks again for "
              "their descriptions; the other LLM answers come from the store")
    return 0


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
    for c in s["calibrations"]:
        sizes = ", ".join(f"{k} {v}" for k, v in c["settings"].items())
        print(f"calibrated ({c['kind']}): {c['model']} on {c['created'][:10]}: {sizes} ({c['report']}/report.md)")
        if c["validation"]:
            from .validate import one_line

            print(f"  expected quality: {one_line(c['validation'])}")
    for p in s["projects"]["failed"]:
        print(f"  failed: {p['name']} {p['token'][:23]} ({p['error']})")
    sub = s.get("subjects") or {}
    if sub.get("families"):
        parts = [f"{n} {w}" for w, n in sub.items() if w != "families"]
        print(f"subjects: {sub['families']} famil{'y' if sub['families'] == 1 else 'ies'} of versions ({', '.join(parts)})"
              + ("; a run asks again for those failed or incomplete" if sub.get("failed") or sub.get("incomplete") else ""))
    for p in s["projects"]["recovered"]:
        n = sum(e["names"] for e in p["entries"].values())
        first = next(iter(p["entries"].values()))["first"]
        print(f"  read with recovery: {p['name']} {p['token'][:23]} ({n} name(s) XML namespaces can't split, read "
              f"as written; first, {first})")
    run = s["latest_run"]
    if run:
        print(f"latest run: {run['outcome'] or 'running or stopped'}, started {run['started']}"
              + (f", {run['llm_calls']} LLM calls" if run["llm_calls"] is not None else ""))


def configure(out: Path, args: argparse.Namespace) -> int:
    """`cameo-ingest config`: show, set or unset the tree's settings (plan CF-02). Setting one
    starts a tree, so that a tree can be configured before its first input."""
    from .config import BY_KEY, SETTINGS, parse_setting, shown

    if args.interactive:
        if args.action:
            print("error: config -i takes no action", file=sys.stderr)
            return 2
        from .interactive import interview

        return interview(out)
    action = args.action or "show"
    if action in ("test", "models"):
        return check_config(out, action, getattr(args, "filter", None))
    if action == "show":
        stored = stored_settings(out)
        print(f"settings of {out}" + ("" if State.exists(out) else " (no tree yet: the defaults)"))
        width = max(len(s.key) for s in SETTINGS)
        for s in SETTINGS:
            value, own = shown(s.key, stored)
            print(f"  {s.key:<{width}}  {value:<18} {'' if own else '(default)':<10} {s.about}")
        print("endpoint: $OPENAI_BASE_URL " + ("set" if os.environ.get("OPENAI_BASE_URL") else "not set (OpenAI)")
              + "; key: $OPENAI_API_KEY " + ("set" if os.environ.get("OPENAI_API_KEY") else "not set"))
        return 0
    try:
        value = parse_setting(args.key, args.value) if action == "set" else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if action == "unset" and args.key not in BY_KEY:
        print(f"error: no setting {args.key!r}; the settings are {', '.join(BY_KEY)}", file=sys.stderr)
        return 2
    state = State(out)
    try:
        state.lock()
        stored = state.settings()
        field = BY_KEY[args.key].field
        if action == "set":
            stored[field] = value
        else:
            stored.pop(field, None)
        state.save_settings(tree_settings(stored).stored())  # retired settings go, with a notice
        print(f"{args.key} = {shown(args.key, state.settings())[0]}")
    finally:
        state.close()
    return 0


def check_config(out: Path, action: str, text: str | None) -> int:
    """`config test` and `config models` (plan CF-03), on the tree's models at $OPENAI_BASE_URL."""
    from . import checks

    settings = tree_settings(stored_settings(out), quiet=True)
    cfg = llm_config(settings)
    endpoint = cfg.base_url or "https://api.openai.com/v1 (OpenAI; $OPENAI_BASE_URL not set)"
    print(f"endpoint: {endpoint}; key: $OPENAI_API_KEY " + ("set" if os.environ.get("OPENAI_API_KEY") else "not set"))
    client = make_client(cfg)
    if action == "models":
        try:
            models = client.models()
        except Exception as e:  # what the endpoint says
            print(f"error: the endpoint lists no models: {type(e).__name__}: {e}", file=sys.stderr)
            return 5
        calibrated = set()
        if State.exists(out):
            st = State(out)
            calibrated = {r["model"] for r in st.calibrations()}
            st.close()
        for model, created in models:
            if text and text.lower() not in model.lower():
                continue
            marks = [m for m, on in (("text model", model == cfg.text_model), ("vision model", model == cfg.vision_model),
                                     ("calibrated", model in calibrated)) if on]
            print(f"  {model}" + (f"  [{', '.join(marks)}]" if marks else ""))
        return 0
    if not cfg.enabled:
        print("error: no model is set: `cameo-ingest config set text-model NAME` (and vision-model, if another "
              "model reads images), or `config set llm off`", file=sys.stderr)
        return 2
    failed = False
    note_models(out, client, cfg)
    for c in checks.run_checks(client, cfg):
        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail} ({c.seconds:.1f} s)")
        failed |= not c.ok and not c.name.startswith("the endpoint lists")
    if failed:
        print("A check failed: see OPENAI_BASE_URL, OPENAI_API_KEY, and `config set text-model` or `vision-model`.",
              file=sys.stderr)
    return 5 if failed else 0


def note_models(out: Path, client: Any, cfg: LLMConfig) -> None:
    """Record, in the tree, the creation time the endpoint gives each configured model, and warn
    when it has changed: a model's identity is its endpoint and id, and this time is the only sign
    the endpoint gives that another model now answers to the id (plan CF-03)."""
    if not State.exists(out):
        return
    try:
        created = dict(client.models())
    except Exception:  # an endpoint that lists no models: nothing to compare
        return
    st = State(out)
    try:
        for model in dict.fromkeys(m for m in (cfg.text_model, cfg.vision_model) if m):
            key, now = f"model:{cfg.base_url or ''}|{model}", created.get(model)
            if now is None:
                continue
            before = st.meta(key)
            if before is not None and before != str(now):
                log.warning("%s at this endpoint reports another creation time (%s, was %s): it may be another "
                            "model under the same id", model, now, before)
            st.set_meta(key, str(now))
    finally:
        st.close()


def shared_store(out: Path, settings: TreeSettings) -> Path:
    """The LLM store's directory (`config.store_dir`), with a tree's own store from before 0.20.2
    copied into it once, so that nothing it paid for is asked again (plan CF-04)."""
    from .config import store_dir
    from .llm import STORE_FILE

    store = store_dir(settings.cache_dir)
    old = out / ".cache" / STORE_FILE
    if not old.is_file() or not State.exists(out) or old.resolve() == (store / STORE_FILE).resolve():
        return store
    st = State(out)
    try:
        if st.meta("store_adopted") is None:
            import sqlite3

            from .llm import ResponseStore

            ResponseStore(store / STORE_FILE).close()  # its tables, if it is new
            db = sqlite3.connect(store / STORE_FILE)
            db.execute("ATTACH DATABASE ? AS old", (str(old),))
            for table in ("responses", "requests"):  # the columns both have: an old store may lack some
                main_cols = [r[1] for r in db.execute(f"PRAGMA main.table_info({table})")]
                old_cols = {r[1] for r in db.execute(f"PRAGMA old.table_info({table})")}
                cols = ", ".join(c for c in main_cols if c in old_cols)
                if cols:
                    db.execute(f"INSERT OR IGNORE INTO main.{table} ({cols}) SELECT {cols} FROM old.{table}")
            db.commit()
            db.close()
            st.set_meta("store_adopted", str(store))
            log.warning("copied this tree's LLM answers (%s) into the shared store, %s", old, store)
    finally:
        st.close()
    return store


def make_client(cfg: LLMConfig) -> Any:
    """The endpoint's client, for checks (tests replace it)."""
    from .llm import OpenAIChat

    return OpenAIChat(cfg)


def tree_of(out: Path | None) -> Path:
    """The tree a command works on (plan CF-01): -o; else $CAMEO_INGEST_TREE; else ./ingest_tree."""
    if out is not None:
        return out
    if os.environ.get("CAMEO_INGEST_DEST") and not os.environ.get("CAMEO_INGEST_TREE"):
        log.warning("CAMEO_INGEST_DEST is retired and ignored: set CAMEO_INGEST_TREE, or give -o")
    return Path(os.environ.get("CAMEO_INGEST_TREE") or DEFAULT_TREE)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not {"-h", "--help", "--version"} & set(argv):
        argv.insert(0, "ingest")  # `cameo-ingest FILE -o OUT` keeps working
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.log_file)
    args.out = tree_of(args.out)
    out: Path = args.out
    if not State.exists(out):
        if args.command in ("run", "status", "prune", "quality", "export", "scan", "projects", "groups", "remove",
                            "restore", "calibrate-vision", "calibrate-text"):
            print(f"error: no output tree at {out}; start one with `add` or `ingest`", file=sys.stderr)
            return 2
        if out.exists() and any(p.name != ".cache" for p in out.iterdir()):
            print(f"error: {out} is not empty and is not a cameo-ingest output tree (no state.sqlite)",
                  file=sys.stderr)
            return 2
    if args.command == "config":
        return configure(out, args)
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
        cache = shared_store(out, TreeSettings.from_stored(state.settings()))
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
    if args.command in ("scan", "projects", "groups", "remove", "restore"):
        return versions_command(out, args)
    if args.command == "calibrate-vision":
        return calibrate_vision(out, args)
    if args.command == "calibrate-text":
        return calibrate_text(out, args)
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

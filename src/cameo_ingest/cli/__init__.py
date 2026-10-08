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
import logging
import os
import sys
from pathlib import Path

from .. import __version__
from ..searchpage import SKETCHES
from ..state import State, StateError
from . import calibration, configure, tree, versions

log = logging.getLogger("cameo_ingest")
DEFAULT_TREE = "ingest_tree"  # in the working directory, when neither -o nor $CAMEO_INGEST_TREE says (plan CF)


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
    sub.add_parser("add", parents=[common, inputs], help="add inputs to the task list").set_defaults(func=tree.add)
    sub.add_parser("run", parents=[common, running], help="process pending inputs and unfinished projects"
                   ).set_defaults(func=tree.run, needs_tree=True)
    sub.add_parser("ingest", parents=[common, inputs, running], help="add inputs, then run (the default)"
                   ).set_defaults(func=tree.run)
    cf = sub.add_parser("config", parents=[common], help="show or change the tree's settings (plan CF)",
                        description="The tree's settings: show them, set one, or unset one (back to its default); "
                                    "export them to JSON, or import them from it. The LLM endpoint and key are "
                                    "$OPENAI_BASE_URL and $OPENAI_API_KEY.")
    cf.set_defaults(func=configure.configure)
    cfs = cf.add_subparsers(dest="action", metavar="ACTION")
    cfs.add_parser("show", help="each setting, its value, and whether it is the tree's own or the default")
    cset = cfs.add_parser("set", help="set a setting")
    cset.add_argument("key", metavar="KEY")
    cset.add_argument("value", metavar="VALUE")
    cunset = cfs.add_parser("unset", help="return a setting to its default")
    cunset.add_argument("key", metavar="KEY")
    cexport = cfs.add_parser("export", help="the tree's own settings as JSON, keyed as `config` names them")
    cexport.add_argument("file", nargs="?", type=Path, metavar="FILE", help="write here (default: print)")
    cimport = cfs.add_parser("import", help="set the settings in a JSON file `config export` wrote (null: unset); "
                                            "a wrong key or value changes nothing")
    cimport.add_argument("file", type=Path, metavar="FILE", help="the JSON file, or - for stdin")
    cfs.add_parser("test", help="check the endpoint and key, and that each model answers (the vision model reads an "
                                "image); exits 5 when a check fails")
    cmodels = cfs.add_parser("models", help="the endpoint's models, those the tree uses or has calibrated marked")
    cmodels.add_argument("filter", nargs="?", metavar="TEXT", help="only models whose id holds TEXT")
    st = sub.add_parser("status", parents=[common], help="what the tree holds, and the latest run")
    st.set_defaults(func=tree.status, needs_tree=True)
    st.add_argument("--json", action="store_true", help="print JSON")
    pr = sub.add_parser("prune", parents=[common],
                        help="drop missing inputs, and the projects that no remaining input contains")
    pr.set_defaults(func=tree.prune, needs_tree=True)
    pr.add_argument("--dry-run", action="store_true", help="only list what would be removed")
    ex = sub.add_parser("export", parents=[common],
                        help="write the catalog of the tree's models for people to search without tools: a "
                             "workbook, a search page (see README, Searching without tools)")
    ex.set_defaults(func=tree.export, needs_tree=True)
    ex.add_argument("--workbook", type=Path, metavar="FILE", help="write the catalog as an Excel workbook (.xlsx)")
    ex.add_argument("--search-page", type=Path, metavar="FILE",
                    help="write the catalog as one self-contained web page (.html) that searches in a browser")
    ex.add_argument("--sketches", choices=SKETCHES, default="none",
                    help="put the diagrams' sketches in the search page: the PNG sketches as WebP, or the SVG "
                         "sketches (default: none)")
    sub.add_parser("scan", parents=[common],
                   help="find the projects in the task list's inputs, and what each says about itself (its save time "
                        "and element ids), building nothing; then `projects` and `groups` can show them"
                   ).set_defaults(func=versions.scan, needs_tree=True)
    pj = sub.add_parser("projects", parents=[common],
                        help="every project in the tree: status, save time, Cameo version, size, where it was found")
    pj.set_defaults(func=versions.projects, needs_tree=True)
    pj.add_argument("--csv", type=Path, metavar="FILE", help="also write the list as CSV")
    gr = sub.add_parser("groups", parents=[common],
                        help="versions of the same model, found by the element ids they share, newest first")
    gr.set_defaults(func=versions.groups, needs_tree=True)
    gr.add_argument("--csv", type=Path, metavar="FILE", help="also write the groups as CSV")
    gr.add_argument("--include-removed", action="store_true", help="compare removed projects too")
    rm = sub.add_parser("remove", parents=[common],
                        help="remove projects from the tree, and keep them out of later runs while their inputs "
                             "remain (their LLM answers stay cached)")
    rm.set_defaults(func=versions.remove, needs_tree=True)
    rm.add_argument("tokens", nargs="+", metavar="TOKEN",
                    help="a project's sha256 (sha256:... or its first 8 or more hex digits)")
    rm.add_argument("--dry-run", action="store_true", help="only list what would be removed")
    rs = sub.add_parser("restore", parents=[common], help="undo `remove`: the next run builds the projects again")
    rs.set_defaults(func=versions.restore, needs_tree=True)
    rs.add_argument("tokens", nargs="+", metavar="TOKEN", help="as for remove")
    about = ("calibrate the sketches to the tree's vision model, as the first run with a model does on its own: "
             "eye charts drawn as sketches are, read by the model, and the sizes they call for (see README, "
             "Calibrating sketches to the vision model). The standard suite's calibration is recorded in the tree, "
             "and runs with that model use it")
    cv = sub.add_parser("calibrate-vision", parents=[common, running], help=about, description=about)
    cv.set_defaults(func=calibration.calibrate_vision, needs_tree=True)
    c = cv.add_argument_group("calibration")
    c.add_argument("--suite", choices=("quick", "standard"), default="standard",
                   help="quick: 11 eye charts, to check a model; standard: 80, and a trial of the image's place, to "
                        "calibrate it (the default)")
    about = ("calibrate the part size to the tree's text model, as the first run with a model does on its own: "
             "reading cards of 6,000 to 24,000 characters, 30 requests (see README, Calibrating the part size to the "
             "text model). It only lowers the part size, for a model that reads 12,000 characters unevenly. The "
             "calibration is recorded in the tree, and runs with that model use it")
    sub.add_parser("calibrate-text", parents=[common, running], help=about, description=about
                   ).set_defaults(func=calibration.calibrate_text, needs_tree=True)
    q = sub.add_parser("quality", help="measure the quality of LLM enrichment (see docs/design/llm-enrichment.md)")
    qs = q.add_subparsers(dest="action", required=True, metavar="ACTION")
    qsample = qs.add_parser("sample", parents=[common], help="draw a spot-check set of requests and answers")
    qsample.set_defaults(func=tree.quality, needs_tree=True)
    qsample.add_argument("--n", type=int, default=30, help="items to draw (default 30)")
    qsample.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    qsample.add_argument("--kind", action="append", metavar="KIND",
                         help="only this kind: diagram_description, module_description (of a large diagram), "
                              "image_description, summary, module_summary (part of a large package); repeatable")
    return ap



def tree_of(out: Path | None) -> Path:
    """The tree a command works on (plan CF-01): -o; else $CAMEO_INGEST_TREE; else ./ingest_tree."""
    if out is not None:
        return out
    if os.environ.get("CAMEO_INGEST_DEST") and not os.environ.get("CAMEO_INGEST_TREE"):
        log.warning("CAMEO_INGEST_DEST is retired and ignored: set CAMEO_INGEST_TREE, or give -o")
    return Path(os.environ.get("CAMEO_INGEST_TREE") or DEFAULT_TREE)



def commands(ap: argparse.ArgumentParser) -> set[str]:
    """The parser's commands."""
    return set(next(a for a in ap._actions if isinstance(a, argparse._SubParsersAction)).choices)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    if argv and argv[0] not in commands(ap) and not {"-h", "--help", "--version"} & set(argv):
        argv.insert(0, "ingest")  # `cameo-ingest FILE -o OUT` keeps working
    args = ap.parse_args(argv)
    args.argv = argv  # recorded with each run
    setup_logging(args.verbose, args.log_file)
    args.out = tree_of(args.out)
    out: Path = args.out
    if not State.exists(out):
        if getattr(args, "needs_tree", False):
            print(f"error: no output tree at {out}; start one with `add` or `ingest`", file=sys.stderr)
            return 2
        if out.exists() and any(p.name != ".cache" for p in out.iterdir()):
            print(f"error: {out} is not empty and is not a cameo-ingest output tree (no state.sqlite)",
                  file=sys.stderr)
            return 2
    try:
        return args.func(out, args)
    except StateError as e:  # the lock held by another process, a newer schema (CQ-009: here, once)
        print(f"error: {e}", file=sys.stderr)
        return 2


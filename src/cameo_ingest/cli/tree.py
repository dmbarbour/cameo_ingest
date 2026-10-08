"""The commands that build and read a tree: `add`, `run`, `ingest`, `status`, `prune`,
`export` and `quality sample` (plan RI-03)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from .. import runner as tree
from ..archive import CANDIDATE_EXTS, ZIP_MAGIC, sniff_xmi
from ..config import ProjectOptions, stored_settings, tree_settings
from ..llm import EnrichmentSession, connect
from ..progress import Progress
from ..runner import Runner
from ..session import llm_config, shared_store
from ..state import State
from .calibration import calibration_for_run
from .common import check_endpoint, open_tree

log = logging.getLogger("cameo_ingest")


NO_MODEL = """error: the tree uses the LLM, but names no model. Either
  - cameo-ingest config set text-model NAME (and vision-model, if another model reads images), or
  - cameo-ingest config set llm off, to ingest without summaries and descriptions,
or set it all up with `cameo-ingest config -i`. The endpoint is $OPENAI_BASE_URL (unset: OpenAI),
its key $OPENAI_API_KEY; `cameo-ingest config models` lists the endpoint's models."""




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



def _candidates(path: Path, out: Path, progress: Progress) -> list[Path]:
    """Files to add for PATH: the file itself, whatever its name; or, under a directory, the files
    named as Cameo's projects and bundles are (`archive.CANDIDATE_EXTS`) that are ZIP archives or
    XMI documents, the output tree and hidden directories left out. The walk reports its
    progress: a directory on a network share can take minutes."""
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
                if f.suffix.lower() not in CANDIDATE_EXTS:
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
    log.info("found %d candidate(s) under %s; %d file(s) skipped by name, %d unreadable",
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



def add(out: Path, args: argparse.Namespace) -> int:
    """`add`: inputs to the task list."""
    with open_tree(out) as state:
        new, old = add_inputs(state, args)
    print(f"added {new} input(s) to the task list of {out} ({old} already listed); `run` processes them")
    return 0


def run(out: Path, args: argparse.Namespace) -> int:
    """`run` and `ingest`: build what is pending, after the endpoint check and, the first time a
    model is used, its calibration."""
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
    llm = EnrichmentSession(cfg, shared_store(out), connect(cfg, args.llm_replay))
    if cfg.enabled and not args.no_preflight and not check_endpoint(llm):
        return 5

    with open_tree(out, lock=True) as state:
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
            code = runner.run(args.argv)
        except KeyboardInterrupt:
            print(f"interrupted; finished work is kept. Continue with: cameo-ingest run -o {out}", file=sys.stderr)
            return 130
        finally:
            signal.signal(signal.SIGTERM, previous)
        counts = state.counts("projects")
        print(f"{len(runner.written)} project(s) written in this run; in {out}: "
              + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
        return code



def _interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt  # SIGTERM stops a run the same way as Ctrl-C



def status(out: Path, args: argparse.Namespace) -> int:
    """`status`: what the tree holds, and the latest run."""
    with open_tree(out) as state:
        print_status(state, args.json)
    return 0


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
            from ..validate import one_line

            print(f"  expected quality: {one_line(c['validation'])}")
    for p in s["projects"]["failed"]:
        print(f"  failed: {p['name']} {p['token'][:23]} ({p['error']})")
    sub = s.get("subjects") or {}
    if sub.get("families"):
        parts = [f"{n} {w}" for w, n in sub.items() if w not in ("families", "topics")]
        print(f"subjects: {sub['families']} famil{'y' if sub['families'] == 1 else 'ies'} of versions ({', '.join(parts)})"
              + ("; a run asks again for those failed or incomplete" if sub.get("failed") or sub.get("incomplete") else "")
              + (f"; topics across models: {sub['topics']}" if sub.get("topics") else ""))
    for p in s["projects"]["recovered"]:
        n = sum(e["names"] for e in p["entries"].values())
        first = next(iter(p["entries"].values()))["first"]
        print(f"  read with recovery: {p['name']} {p['token'][:23]} ({n} name(s) XML namespaces can't split, read "
              f"as written; first, {first})")
    run = s["latest_run"]
    if run:
        print(f"latest run: {run['outcome'] or 'running or stopped'}, started {run['started']}"
              + (f", {run['llm_calls']} LLM calls" if run["llm_calls"] is not None else ""))



def prune(out: Path, args: argparse.Namespace) -> int:
    """`prune`: drop missing inputs, and the projects no remaining input contains."""
    with open_tree(out, lock=True) as state:
        removed = tree.prune(state, out, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    print(f"{verb} {len(removed['inputs'])} missing input(s) and {len(removed['projects'])} project(s)")
    for p in removed["projects"]:
        print(f"  {p['name']} {p['token'][:23]}")
    return 0


def export(out: Path, args: argparse.Namespace) -> int:
    """`export`: the tree's catalogs as a workbook and a search page (plan KX-06)."""
    from .. import __version__, catalog, searchpage, workbook

    if not (args.workbook or args.search_page):
        print("error: export needs --workbook FILE, --search-page FILE or both", file=sys.stderr)
        return 2
    missing: list[str] = []
    with open_tree(out) as state:
        inputs = catalog.export_inputs(state, out)  # once for both (CQ-006)
        if args.workbook:
            rows = workbook.write_workbook(args.workbook, catalog.tree_catalogs(state, out, missing, Progress()),
                                           __version__, inputs)
            print(f"wrote {args.workbook} ({args.workbook.stat().st_size / 1e6:.1f} MB): "
                  + ", ".join(f"{n:,} {k}" for k, n in rows.items()))
        if args.search_page:
            missing.clear()
            counts = searchpage.write_search_page(
                args.search_page, catalog.tree_catalogs(state, out, missing, Progress(), chunks=True), __version__,
                args.sketches, inputs)
            print(f"wrote {args.search_page} ({args.search_page.stat().st_size / 1e6:.1f} MB): "
                  f"{counts['items']:,} items from {counts['projects']:,} models"
                  + (f", {counts['sketches']:,} sketches ({counts['sketch bytes'] / 1e6:.1f} MB)"
                     if counts["sketches"] else ""))
    if missing:
        print(f"note: {len(missing)} project(s) were made before catalogs existed and are left out: "
              f"{', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}; `run` makes them again", file=sys.stderr)
    return 0



def quality(out: Path, args: argparse.Namespace) -> int:
    """`quality sample`: a spot-check set of LLM requests and answers."""
    from .. import quality as q

    try:
        set_dir = q.sample(out, shared_store(out), n=args.n, seed=args.seed, kinds=args.kind)
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

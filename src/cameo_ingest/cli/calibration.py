"""`calibrate-vision` and `calibrate-text`, and the calibrations a run makes first when the
tree has none for its models (plans VC, VA, TC)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ..config import IMAGE_PIXELS, TreeSettings, stored_settings, tree_settings
from ..llm import EnrichmentSession, connect
from ..progress import Progress
from ..session import llm_config, shared_store
from ..state import State
from ..treefiles import PROJECTS
from .common import check_endpoint, open_tree

log = logging.getLogger("cameo_ingest")
INTERRUPTED = "interrupted; the answers so far are stored, so running again asks only for the rest"


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
    from .. import textcal

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
    from .. import calibrate

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
    from .. import validate

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
    from .. import textcal

    settings = tree_settings(stored_settings(out))
    cfg = llm_config(settings)
    cfg.vision_model = None  # text only
    if settings.no_llm or not cfg.text_model:
        print("error: calibrate-text needs a text model: cameo-ingest config set text-model NAME", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, shared_store(out), connect(cfg, args.llm_replay))
    if not args.no_preflight and not check_endpoint(llm):
        return 5
    try:
        with open_tree(out, lock=True) as state:
            result = textcal.calibrate_text(out, state, llm, settings.llm_concurrency or 1,
                                            Progress(heartbeat=args.heartbeat))
    except KeyboardInterrupt:
        print(INTERRUPTED, file=sys.stderr)
        return 130
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
    from .. import calibrate

    settings = tree_settings(stored_settings(out))
    cfg = llm_config(settings)
    cfg.text_model = None  # images only
    if settings.no_llm or not cfg.vision_model:
        print("error: calibrate-vision needs a vision model: cameo-ingest config set vision-model NAME (or "
              "text-model, which reads images too unless another is set)", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, shared_store(out), connect(cfg, args.llm_replay))
    if not args.no_preflight and not check_endpoint(llm):
        return 5
    try:
        with open_tree(out, lock=True) as state:
            using = settings.calibrated(calibrate.recorded(state, cfg))
            result = calibrate.calibrate_model(out, state, llm, args.suite, settings.image_pixels or IMAGE_PIXELS,
                                               using, settings.llm_concurrency or 1, Progress(heartbeat=args.heartbeat),
                                               settings.image_first)
    except KeyboardInterrupt:
        print(INTERRUPTED, file=sys.stderr)
        return 130
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
    with open_tree(out, lock=True) as state:
        report_validation(state, llm, settings.calibrated(result.settings), result.dest, settings.llm_concurrency or 1,
                          Progress(heartbeat=args.heartbeat))
    if _sizes(settings.calibrated(result.settings)) != _sizes(using):
        sketches = sum(1 for _ in (out / PROJECTS).glob("*/diagrams/**/*.png"))
        print(f"the next run with {cfg.vision_model} draws the tree's {sketches:,} sketches again and asks again for "
              "their descriptions; the other LLM answers come from the store")
    return 0


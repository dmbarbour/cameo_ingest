"""`calibrate-vision` and `calibrate-text`, and the calibrations a run makes first when the
tree has none for its models (plans VC, VA, TC)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import IMAGE_PIXELS, PART_CHARS, TreeSettings, stored_settings, tree_settings
from ..llm import EnrichmentSession, connect
from ..progress import Progress
from ..session import llm_config, shared_store
from ..state import State
from ..treefiles import PROJECTS
from .common import check_endpoint, open_tree

log = logging.getLogger("cameo_ingest")
INTERRUPTED = "interrupted; the answers so far are stored, so running again asks only for the rest"


def calibration_for_run(out: Path, state: State, llm: EnrichmentSession, settings: TreeSettings,
                        progress: Progress, calibrate: bool = True) -> tuple[dict[str, Any] | None, dict[str, bool]]:
    """The models' calibrations for a run: the first text model's (plan TC) and the first vision
    model's (plan VA), as settings, which draw the sketches and cut the parts (None: the
    uncalibrated defaults); and each vision fallback's image order. Every model of each list is
    calibrated, alone (`EnrichmentSession.only`); a fallback that reads best with larger sketches
    or smaller parts than the first's gets a warning (FM-10, FM-D3). `calibrate` off is for tests."""
    if not calibrate:
        return None, {}
    cfg = llm.cfg
    found: dict[str, Any] = {}
    for n, model in enumerate(cfg.text_models):
        with llm.only(model, "text"):
            got = text_calibration_for_run(out, state, llm, settings, progress) or {}
        cut = settings.calibrated(found).part_chars or PART_CHARS[1]  # the first model's part size
        if n == 0:
            found.update(got)
        elif got.get("part_chars") and got["part_chars"] < cut:
            log.warning("the text fallback %s reads parts of up to %s characters evenly, and this tree cuts them "
                        "for %s, at %s: its summaries may be poorer", model, f"{got['part_chars']:,}",
                        cfg.text_model, f"{cut:,}")
    orders: dict[str, bool] = {}
    for n, model in enumerate(cfg.vision_models):
        drawn = settings.calibrated(found)  # the first vision model's sizes, once it is calibrated
        with llm.only(model, "vision"):
            got = vision_calibration_for_run(out, state, llm, settings, progress, drawn=drawn if n else None) or {}
        if n == 0:
            found.update(got)
            continue
        orders[model] = got.get("image_first", True)
        own = TreeSettings().calibrated(got).sketch
        if any(o > d for o, d in zip(own, drawn.sketch, strict=True)):
            log.warning("the vision fallback %s reads sketches best with text of %s px, arrowheads of %s px and "
                        "lines of %s px; this tree draws them for %s (%s, %s, %s): its descriptions may be poorer",
                        model, *own, cfg.vision_model, *drawn.sketch)
    return found or None, orders


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
                               progress: Progress, drawn: TreeSettings | None = None) -> dict[str, Any] | None:
    """The vision model's calibration for a run (plan VA): the tree's record, made first when it
    has none and sketches are drawn. None: the uncalibrated defaults. `drawn`, for a fallback:
    the sizes the tree draws to (the first model's), which its validation reads (FM-10)."""
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
            log.warning("the calibration of %s is incomplete (%s): %s; see %s", cfg.vision_model, result.problem,
                        "this run draws to the uncalibrated defaults" if drawn is None else
                        "as a fallback, it gets the image first, as by default", result.dest / "report.md")
            return None
        print(f"calibrated to {cfg.vision_model}: " + ", ".join(f"{k} {v}" for k, v in result.settings.items())
              + f" (the tree's own settings win; see {result.dest / 'report.md'})", file=sys.stderr)
        found, report_dir = result.settings, result.dest
    sizes = settings.calibrated(found) if drawn is None else replace(drawn, image_first=found.get("image_first"))
    report_validation(state, llm, sizes, report_dir, settings.llm_concurrency or 1, progress)
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
    model = args.model or cfg.text_model
    if model not in cfg.text_models:
        print(f"error: {model} is not one of the text models ({', '.join(cfg.text_models)})", file=sys.stderr)
        return 2
    llm = EnrichmentSession(cfg, shared_store(out), connect(cfg, args.llm_replay))
    if not args.no_preflight and not check_endpoint(llm):
        return 5
    try:
        with open_tree(out, lock=True) as state, llm.only(model, "text"):  # that model alone (FM-10)
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
    print(f"recorded: runs with {model} use this part size" if model == cfg.text_model else
          f"recorded: {model} is a fallback; the tree's parts are cut for {cfg.text_model}")
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
    model = args.model or cfg.vision_model
    if model not in cfg.vision_models:
        print(f"error: {model} is not one of the vision models ({', '.join(cfg.vision_models)})", file=sys.stderr)
        return 2
    first = model == cfg.vision_model
    llm = EnrichmentSession(cfg, shared_store(out), connect(cfg, args.llm_replay))
    if not args.no_preflight and not check_endpoint(llm):
        return 5
    try:
        with open_tree(out, lock=True) as state, llm.only(model, "vision"):  # that model alone (FM-10)
            drawn = settings.calibrated(calibrate.recorded(state, cfg))  # the first model's sizes
            using = drawn if first else settings.calibrated(calibrate.recorded(state, llm.cfg))
            result = calibrate.calibrate_model(out, state, llm, args.suite, settings.image_pixels or IMAGE_PIXELS,
                                               using, settings.llm_concurrency or 1, Progress(heartbeat=args.heartbeat),
                                               settings.image_first if first else None)
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
    print(f"recorded: runs with {model} use these settings" if first else
          f"recorded: {model} is a fallback; it reads the sketches drawn for {cfg.vision_model}, in its own image order")
    sizes = (settings.calibrated(result.settings) if first
             else replace(drawn, image_first=result.settings.get("image_first")))  # what it will read (FM-D3)
    with open_tree(out, lock=True) as state, llm.only(model, "vision"):
        report_validation(state, llm, sizes, result.dest, settings.llm_concurrency or 1,
                          Progress(heartbeat=args.heartbeat))
    if first and _sizes(settings.calibrated(result.settings)) != _sizes(using):
        sketches = sum(1 for _ in (out / PROJECTS).glob("*/diagrams/**/*.png"))
        print(f"the next run with {cfg.vision_model} draws the tree's {sketches:,} sketches again and asks again for "
              "their descriptions; the other LLM answers come from the store")
    return 0


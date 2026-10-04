"""Calibrating sketches to the configured vision model (plan VC-03, VC-04).

`ask` has the model read eye charts (`eyechart.py`) through the session, so that answers are
stored and a rerun costs nothing; `summarize` fits what it read; `recommend` derives the sketch
settings from the measurements alone. The tree's current values are shown beside them but never
preferred, and no cache is a reason to keep one: a change redraws the sketches, and asks again
for their descriptions, as it should (the maintainer's policy, 2026-10-03).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import eyechart as ec
from .config import IMAGE_PIXELS, MODULES, SKETCH, TreeSettings
from .llm import EnrichmentSession, LLMConfig
from .progress import QUIET, Progress
from .prompts import Slot, Template
from .sketch import SketchStyle
from .state import State
from .vision import PATCH_PX

_CARD = Slot("CARD", "image", "the eye chart: random codes and numbers, or numbered boxes joined by arrows")
TEMPLATES = {  # outside prompts.CURRENT: calibration changes no project's options
    family: Template(id=f"eye-{family}", version=1,
                     purpose="An eye chart for calibrating sketches to the vision model (plan VC); scored, not stored.",
                     text=prompt, slots=(_CARD,), image_first=True)
    for family, prompt in (("read", ec.READ_PROMPT), ("arrows", ec.ARROWS_PROMPT))
}
SUITE_VERSION = 1  # the cards and rules a calibration was made with: a new version calibrates again
ARROWS_PASS = 0.95  # arrows the right way round, for an arrowhead size and line width to pass
DENSITY_PASS = 0.9  # connections found (either way round), for a number of shapes to pass
FONT_MARGIN = 1.3  # the font's size over the 90% threshold
ORDER_GAIN = 0.05  # how much better the image after the text must read to be put there
FLAT = 1.15  # thresholds within this of the smallest are "the same"
PATCH_AREA = PATCH_PX * PATCH_PX


def ask(llm: EnrichmentSession, cards: list[ec.Card], concurrency: int = 4, progress: Progress = QUIET,
        label: str = "eye charts", image_first: bool = True, trial: bool = False) -> list[dict[str, Any]]:
    """Each card drawn, asked (the image before or after the text) and scored. `trial`: asked
    to choose the image's place, and left out of the other measures."""
    def one(card: ec.Card) -> dict[str, Any]:
        drawn = ec.render(card)
        template = TEMPLATES["read" if card.family == "read" else "arrows"]
        res = llm.ask(template, {}, image=drawn.png, mime="image/png", project="calibration:vision",
                      inputs=(card.id,), image_first=image_first)
        reply = res[0] if res else None
        answer = ec.parse(reply)
        return {**ec.card_record(drawn), "reply": reply, "answer": answer, "asked": res is not None,
                "image_first": image_first, "trial": trial, **ec.score(card, drawn.truth, answer)}

    with progress.phase(label, len(cards), "card") as ph, ThreadPoolExecutor(max(1, concurrency)) as pool:
        futures = [pool.submit(one, card) for card in cards]
        for done in as_completed(futures):  # counted as answered, not in order: a slow card holds nothing up
            done.result()
            ph.advance()
    return [f.result() for f in futures]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def order(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The trial of the image's place: mean scores each way, and the mean difference per card
    (after the text, less before) with its standard error; None without a trial."""
    first = {r["id"]: r["score"] for r in results if r.get("trial") and r["image_first"]}
    later = {r["id"]: r["score"] for r in results if r.get("trial") and not r["image_first"]}
    pairs = [(first[i], later[i]) for i in first if i in later]
    if not pairs:
        return None
    diffs = [b - a for a, b in pairs]
    mean = _mean(diffs)
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)) if len(diffs) > 1 else 0.0
    return {"cards": len(pairs), "image_first": _mean([a for a, _ in pairs]), "text_first": _mean([b for _, b in pairs]),
            "difference": mean, "se": sd / math.sqrt(len(diffs))}


def image_first(trial: dict[str, Any] | None) -> bool:
    """The image goes after the text only when that reads clearly better: by at least 5 points,
    and by more than twice the standard error of the difference; otherwise first, as by default."""
    return not (trial is not None and trial["difference"] >= ORDER_GAIN and trial["difference"] > 2 * trial["se"])


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """The reading thresholds per image area; arrows per arrowhead and line; connections per
    density (all but the trial of the image's place); and that trial."""
    read: dict[float, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    arrows: dict[tuple[float, int], list[dict]] = defaultdict(list)
    density: dict[int, list[dict]] = defaultdict(list)
    for r in results:
        if r.get("trial"):
            continue
        if r["family"] == "read":
            read[r["area"]][r["font_px"]].append(r["score"])
        elif r["family"] == "arrows":
            arrows[(r["arrow_px"], r["line_px"])].append(r)
        else:
            density[r["count"]].append(r)
    areas = []
    for area in sorted(read):
        points = [(f, _mean(s)) for f, s in sorted(read[area].items())]
        areas.append({"area": area, "points": points, "threshold": ec.threshold(points)})

    def arrow_stats(rs: list[dict]) -> dict[str, float]:
        items = sum(r["items"] for r in rs) or 1
        right, rev = sum(r["right"] for r in rs) / items, sum(r["reversed"] for r in rs) / items
        return {"right": right, "reversed": rev, "found": right + rev, "cards": len(rs)}

    return {"read": areas,
            "arrows": [{"arrow_px": a, "line_px": ln, **arrow_stats(rs)} for (a, ln), rs in sorted(arrows.items())],
            "density": [{"shapes": n, **arrow_stats(rs)} for n, rs in sorted(density.items())],
            "order": order(results),
            "unreadable": sum(1 for r in results if r["asked"] and r["answer"] is None),
            "unasked": sum(1 for r in results if not r["asked"]), "cards": len(results)}


@dataclass
class Recommendation:
    setting: str  # as the tree's settings name it
    current: Any
    recommended: Any
    measured: str  # what the cards showed
    why: str

    @property
    def changes(self) -> bool:
        return self.recommended != self.current


def _patches(pixels: float) -> int:
    """`pixels` rounded down to whole patches (at least one)."""
    return max(1, int(pixels // PATCH_AREA)) * PATCH_AREA


def measure(llm: EnrichmentSession, name: str, pixels: int, concurrency: int = 4, progress: Progress = QUIET,
            fixed_order: bool | None = None) -> tuple[list[ec.Card], list[dict[str, Any]]]:
    """A suite's cards and their results, in stages, so that nothing measured depends on the
    tree's current sizes:
    - the standard suite first tries the image both before and after the text, unless the tree
      fixes its place (`fixed_order`), and asks the rest in the order that reads better;
    - the reading cards, which decide the budget and the font;
    - the arrow and density cards, at that font and budget."""
    results: list[dict[str, Any]] = []
    trial: list[ec.Card] = []
    first_order = True if fixed_order is None else fixed_order
    if name == "standard" and fixed_order is None:
        trial = ec.order_trial(pixels)
        for before in (True, False):
            results += ask(llm, trial, concurrency, progress, "eye charts: the image " + ("first" if before else
                           "after the text"), image_first=before, trial=True)
        first_order = image_first(order(results))
    first = ec.reading(name, pixels)
    results += ask(llm, first, concurrency, progress, "eye charts: reading", first_order)
    chosen = {r.setting: r.recommended for r in _reading(summarize(results), pixels, SKETCH[0])}
    style = SketchStyle(chosen["sketch_font_px"], *SKETCH[1:])
    second = ec.drawings(name, chosen.get("image_pixels", pixels), style)
    results += ask(llm, second, concurrency, progress, "eye charts: arrows and density", first_order)
    shown = {c.id: c for c in trial + first + second}
    return list(shown.values()), results


def _reading(summary: dict[str, Any], pixels: int, font: int) -> list[Recommendation]:
    """The budget and the font, from the reading cards; the default font when nothing was read."""
    reads = {a["area"]: a["threshold"] for a in summary["read"]}
    known = [t for t in reads.values() if t is not None]
    if not known:
        return [Recommendation("sketch_font_px", font, SKETCH[0], "no font size was read by 90%",
                               "the model reads none of the eye charts: check its replies before calibrating")]
    floor = min(known)
    flat = {a for a, t in reads.items() if t is not None and t <= FLAT * floor}  # areas read as well as any
    shown = ", ".join(f"{a:g}x: {f'{t:g} px' if t is not None else 'none'}" for a, t in sorted(reads.items()))
    measured = f"90% read at, by image area: {shown}"
    areas = sorted(reads)
    if len(flat) == len(reads):
        # The range can't tell these apart (plan VA): either way, more pixels read no smaller text.
        recs = [Recommendation("image_pixels", pixels, pixels, measured,
                               f"the threshold doesn't grow with the image from {areas[0]:g} to {areas[-1]:g} "
                               "times the budget: the model reads at native resolution, or its host's own budget "
                               f"is at least {areas[-1]:g} times this one. More pixels cost more tokens and read "
                               "no smaller text, so the budget is a matter of cost, kept as configured")]
        threshold_px = reads.get(1.0) or floor
    else:  # the host shrinks images to a budget of its own: the largest area read as well as the smallest
        held = [a for k, a in enumerate(areas) if all(b in flat for b in areas[:k + 1])]
        best = max(held) if held else max(flat)
        why = (f"text reads as well up to {best:g} times the budget and worse beyond: the host shrinks larger "
               "images to about that budget")
        if best == areas[0]:
            why = (f"text reads worse beyond {best:g} times the budget, the smallest size tested: the host shrinks "
                   "images to at most that budget, perhaps less; the smallest size tested is used")
        recs = [Recommendation("image_pixels", pixels, _patches(best * pixels), measured, why)]
        threshold_px = reads[best]
    needed = math.ceil(FONT_MARGIN * threshold_px)
    recs.append(Recommendation("sketch_font_px", font, needed, f"90% read at {threshold_px:g} px",
                               f"{FONT_MARGIN:g} times the threshold (the current size is "
                               f"{font / threshold_px:.2f} times it)"))
    return recs


def recommend(summary: dict[str, Any], pixels: int, sketch: tuple[int, float, int] = SKETCH,
              modules: tuple[int, int, int] = MODULES, first: bool = True) -> list[Recommendation]:
    """The settings the measurements call for, derived from them alone: the tree's current values
    are shown beside them, never preferred. What the cards leave undecided falls back to the tool's
    uncalibrated defaults (`SKETCH`, `MODULES`), and the budget of a model that
    reads at native resolution, a matter of cost, stays as configured."""
    font, arrow, line = sketch
    recs = _reading(summary, pixels, font)
    if not any(a["threshold"] is not None for a in summary["read"]):
        return recs
    arrows = summary["arrows"]
    passing = [a for a in arrows if a["right"] >= ARROWS_PASS]
    if passing:
        best_a = min(passing, key=lambda a: (a["line_px"], a["arrow_px"]))
        pick = (best_a["arrow_px"], best_a["line_px"])
        why = f"the thinnest lines and smallest heads read {ARROWS_PASS:.0%} the right way round"
    elif arrows:
        pick = SKETCH[1:]
        top = max(a["right"] for a in arrows)
        why = (f"none reaches {ARROWS_PASS:.0%} (the best, {top:.0%}): the default sizes; descriptions get "
               "every connection's direction as text")
    else:
        pick, why = SKETCH[1:], "not measured (no arrow card fits this font and budget): the default sizes"
    chosen = next((a for a in arrows if (a["arrow_px"], a["line_px"]) == pick), None)
    table = (f"{pick[0]:g} px heads, {pick[1]} px lines: {chosen['right']:.0%} the right way round, "
             f"{chosen['reversed']:.0%} reversed (see Arrows)" if chosen is not None else "see Arrows")
    recs.append(Recommendation("sketch_arrow_px", arrow, pick[0], table, why))
    recs.append(Recommendation("sketch_line_px", line, pick[1], table, why))
    # The modules' size is judged on connections found, either way round: a direction misread is the
    # arrows' measure, and happens among few shapes as among many (plan VC, results).
    dens = summary["density"]
    # Connections can only be harder to find among more shapes: a dip at one size is averaged out.
    fitted = list(zip([d["shapes"] for d in dens], reversed(ec.monotone([d["found"] for d in reversed(dens)])),
                      strict=True))
    table = "connections found among " + ", ".join(f"{d['shapes']} shapes: {d['found']:.0%}" for d in dens)
    ok = [n for n, found in fitted if found >= DENSITY_PASS]
    if ok:
        top_n = max(ok)
        rec = (top_n, min(MODULES[1], top_n), top_n)
        why = (f"connections are found among up to {top_n} shapes"
               + (" (the most tested at this font and budget)" if top_n == max(n for n, _ in fitted)
                  else ", and missed among more"))
    else:
        rec = MODULES
        why = ("connections are missed even among the fewest shapes: the default modules; look at why"
               if dens else "not measured: the default modules")
    recs.append(Recommendation("diagram_modules", ":".join(map(str, modules)), ":".join(map(str, rec)), table, why))
    trial = summary.get("order")
    if trial is not None:
        later = not image_first(trial)
        recs.append(Recommendation(
            "image_first", first, not later,
            f"{trial['image_first']:.0%} read with the image first, {trial['text_first']:.0%} after the text, over "
            f"{trial['cards']} cards",
            "clearly better after the text" if later else "no clearer after the text: the image first, as by default"))
    return recs


def calibrated_settings(recs: list[Recommendation]) -> dict[str, Any]:
    """The recommendations as tree settings, for the calibration's record."""
    out = {r.setting: r.recommended for r in recs}
    if "sketch_arrow_px" in out:
        out["sketch_arrow_px"] = float(out["sketch_arrow_px"])
    return out


def render_report(model: str, endpoint: str | None, suite: str, summary: dict[str, Any],
                  recs: list[Recommendation], cost_note: str = "") -> str:
    lines = [f"# Vision calibration: {model}", "",
             f"Endpoint `{endpoint or 'the OpenAI default'}`, suite `{suite}`: {summary['cards']} eye charts"
             + (f", {summary['unreadable']} replies unreadable" if summary["unreadable"] else "")
             + (f", {summary['unasked']} not asked (budget or failures)" if summary["unasked"] else "") + ".", "",
             "## Recommendations", "", "| Setting | Current | Recommended | Measured | Why |", "|---|---|---|---|---|"]
    for r in recs:
        mark = " **(change)**" if r.changes else ""
        lines.append(f"| `{r.setting}` | {r.current} | {r.recommended}{mark} | {r.measured} | {r.why} |")
    lines += ["", "## Reading", "", "Share of tokens read, by font size (px), per image area (times the budget):", "",
              "| Area | " + " | ".join(f"{f} px" for f, _ in (summary["read"][0]["points"] if summary["read"] else []))
              + " | 90% at |", "|---|" + "---|" * (len(summary["read"][0]["points"]) + 1 if summary["read"] else 1)]
    for a in summary["read"]:
        lines.append(f"| {a['area']:g}x | " + " | ".join(f"{s:.2f}" for _, s in a["points"])
                     + f" | {a['threshold'] if a['threshold'] is not None else 'none'} |")
    lines += ["", "## Arrows", "", "| Arrowhead | Line | Right | Reversed |", "|---|---|---|---|"]
    lines += [f"| {a['arrow_px']:g} px | {a['line_px']} px | {a['right']:.0%} | {a['reversed']:.0%} |"
              for a in summary["arrows"]]
    lines += ["", "## Density", "", "| Shapes | Connections found | Right way round | Reversed |", "|---|---|---|---|"]
    lines += [f"| {d['shapes']} | {d['found']:.0%} | {d['right']:.0%} | {d['reversed']:.0%} |"
              for d in summary["density"]]
    trial = summary.get("order")
    if trial is not None:
        lines += ["", "## The image's place", "",
                  f"{trial['cards']} cards asked both ways: {trial['image_first']:.0%} read with the image first, "
                  f"{trial['text_first']:.0%} with it after the text (difference {trial['difference']:+.0%}, "
                  f"standard error {trial['se']:.0%}). The other cards were asked with the image "
                  + ("first." if image_first(trial) else "after the text.")]
    if cost_note:
        lines += ["", cost_note]
    return "\n".join(lines) + "\n"


def problem(summary: dict[str, Any]) -> str | None:
    """Why a calibration can't be trusted, or None."""
    asked = summary["cards"] - summary["unasked"]
    if summary["unasked"]:
        return f"{summary['unasked']} of {summary['cards']} eye charts were not asked (failures or the call budget)"
    if summary["unreadable"] * 2 > asked:
        return f"{summary['unreadable']} of {asked} replies could not be read"
    if not any(a["threshold"] for a in summary["read"]):
        return "the model read no font size on the eye charts"
    return None


def recorded(state: State, cfg: LLMConfig) -> dict[str, Any] | None:
    """The settings of the configured vision model's calibration in this tree, if it has one."""
    row = state.calibration(cfg.base_url or "", cfg.vision_model or "", SUITE_VERSION) if cfg.vision_model else None
    return json.loads(row["settings"]) if row else None


@dataclass
class Outcome:
    dest: Path  # the report's directory
    recs: list[Recommendation]
    problem: str | None
    settings: dict[str, Any] | None  # as recorded; None when not recorded


def calibrate_model(out: Path, state: State, llm: EnrichmentSession, suite: str, pixels: int, using: TreeSettings,
                    concurrency: int = 1, progress: Progress = QUIET, fixed_order: bool | None = None) -> Outcome:
    """Measure the session's vision model with a suite of eye charts, starting at a budget of
    `pixels`, and report. The standard suite's calibration, when it can be trusted, is recorded in
    the tree for runs with that model. `using`: the settings runs use now, shown beside the
    recommendations; `fixed_order`: the image's place, when the tree sets it."""
    cfg = llm.cfg
    model = cfg.vision_model or ""
    cards, results = measure(llm, suite, pixels, concurrency, progress, fixed_order)
    summary = summarize(results)
    recs = recommend(summary, pixels, using.sketch, using.modules, using.image_first is not False)
    for r in recs:
        if r.setting == "image_pixels":
            r.current = using.image_pixels or IMAGE_PIXELS
    stored_answers = llm.outcomes["cached"] + llm.outcomes["replayed"]
    report = render_report(model, cfg.base_url, suite, summary, recs,
                           f"{llm.calls} requests sent; {stored_answers} answered from the store.")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    dest = out / "calibration" / f"{name}-{dt.datetime.now(dt.UTC).date().isoformat()}"
    save(dest, results, summary, recs, report, cards)
    why = problem(summary)
    settings = None
    if why is None and suite == "standard":
        settings = calibrated_settings(recs)
        state.save_calibration(cfg.base_url or "", model, SUITE_VERSION, settings, summary,
                               dest.relative_to(out).as_posix())
    return Outcome(dest, recs, why, settings)


def save(out_dir: Path, results: list[dict[str, Any]], summary: dict[str, Any], recs: list[Recommendation],
         report: str, cards: list[ec.Card]) -> None:
    (out_dir / "cards").mkdir(parents=True, exist_ok=True)
    for card in cards:
        (out_dir / "cards" / f"{card.id}.png").write_bytes(ec.render(card).png)
    (out_dir / "results.json").write_text(json.dumps(
        {"summary": summary, "recommendations": [r.__dict__ for r in recs], "cards": results},
        indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(report, encoding="utf-8")

"""Calibrating sketches to the configured vision model (plan VC-03, VC-04).

`ask` has the model read eye charts (`eyechart.py`) through the session, so that answers are
stored and a rerun costs nothing; `summarize` fits what it read; `recommend` derives the sketch
settings. A recommendation keeps the current value unless the measurement shows it falls short:
every change redraws the sketches and asks again for every description of them, so a setting
changes only to fix what fails. The report shows each measured limit beside the current value.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import eyechart as ec
from .config import MODULES, SKETCH
from .llm import EnrichmentSession
from .progress import QUIET, Progress
from .prompts import Slot, Template
from .vision import PATCH_PX

_CARD = Slot("CARD", "image", "the eye chart: random codes and numbers, or numbered boxes joined by arrows")
TEMPLATES = {  # outside prompts.CURRENT: calibration changes no project's options
    family: Template(id=f"eye-{family}", version=1,
                     purpose="An eye chart for calibrating sketches to the vision model (plan VC); scored, not stored.",
                     text=prompt, slots=(_CARD,), image_first=True)
    for family, prompt in (("read", ec.READ_PROMPT), ("arrows", ec.ARROWS_PROMPT))
}
ARROWS_PASS = 0.95  # arrows the right way round, for an arrowhead size and line width to pass
DENSITY_PASS = 0.9  # connections found (either way round), for a number of shapes to pass
FONT_MARGIN = 1.3  # the font's size over the 90% threshold
FLAT = 1.15  # thresholds within this of the smallest are "the same"
PATCH_AREA = PATCH_PX * PATCH_PX


def ask(llm: EnrichmentSession, cards: list[ec.Card], concurrency: int = 4, progress: Progress = QUIET,
        ) -> list[dict[str, Any]]:
    """Each card drawn, asked and scored."""
    def one(card: ec.Card) -> dict[str, Any]:
        drawn = ec.render(card)
        template = TEMPLATES["read" if card.family == "read" else "arrows"]
        res = llm.ask(template, {}, image=drawn.png, mime="image/png", project="calibration:vision",
                      inputs=(card.id,))
        reply = res[0] if res else None
        answer = ec.parse(reply)
        return {**ec.card_record(drawn), "reply": reply, "answer": answer, "asked": res is not None,
                **ec.score(card, drawn.truth, answer)}

    with progress.phase("eye charts", len(cards), "card") as ph, ThreadPoolExecutor(max(1, concurrency)) as pool:
        futures = [pool.submit(one, card) for card in cards]
        for done in as_completed(futures):  # counted as answered, not in order: a slow card holds nothing up
            done.result()
            ph.advance()
    return [f.result() for f in futures]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """The reading thresholds per image area; arrows per arrowhead and line; connections per density."""
    read: dict[float, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    arrows: dict[tuple[float, int], list[dict]] = defaultdict(list)
    density: dict[int, list[dict]] = defaultdict(list)
    for r in results:
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


def recommend(summary: dict[str, Any], pixels: int, sketch: tuple[int, float, int] = SKETCH,
              modules: tuple[int, int, int] = MODULES) -> list[Recommendation]:
    """The settings the measurements call for, each kept unless it falls short."""
    font, arrow, line = sketch
    reads = {a["area"]: a["threshold"] for a in summary["read"]}
    known = [t for t in reads.values() if t is not None]
    if not known:
        return [Recommendation("sketch_font_px", font, font, "no font size was read by 90%",
                               "the model reads none of the eye charts: check its replies before calibrating")]
    floor = min(known)
    flat = sorted(a for a, t in reads.items() if t is not None and t <= FLAT * floor)  # areas read as the best
    shown = ", ".join(f"{a:g}x: {f'{t:g} px' if t is not None else 'none'}" for a, t in sorted(reads.items()))
    measured = f"90% read at, by image area: {shown}"
    if 1.0 in flat or not any(a < 1 for a in flat):
        if len(flat) == len(reads):
            why = ("the threshold doesn't grow with the image: the model reads at native resolution, so a larger "
                   "budget would cost tokens and read no smaller text")
        else:
            why = (f"the threshold holds up to {max(flat):g} times the budget and grows beyond: the host shrinks "
                   "larger images")
        recs = [Recommendation("image_pixels", pixels, pixels, measured, why)]
        threshold_px = reads.get(1.0) or floor
    else:  # text reads smaller in smaller images: the host's budget is below ours
        best = max(a for a in flat if a < 1)
        recs = [Recommendation("image_pixels", pixels, _patches(best * pixels), measured,
                               f"text reads smaller at {best:g} times the budget: the host shrinks images of the "
                               "current budget")]
        threshold_px = reads[best]
    needed = math.ceil(FONT_MARGIN * threshold_px)
    recs.append(Recommendation(
        "sketch_font_px", font, max(font, needed),
        f"90% read at {threshold_px:g} px: {needed} px with a {FONT_MARGIN:g}x margin",
        f"{font} px is {font / threshold_px:.2f}x the threshold: "
        + ("the margin holds" if font >= needed else f"short of the {FONT_MARGIN:g}x margin")))
    arrows = summary["arrows"]
    passing = [a for a in arrows if a["right"] >= ARROWS_PASS]
    current = next((a for a in arrows if (a["arrow_px"], a["line_px"]) == (arrow, line)), None)
    table = (f"{arrow:g} px heads, {line} px lines: {current['right']:.0%} the right way round, "
             f"{current['reversed']:.0%} reversed (see Arrows)" if current is not None else "see Arrows")
    # Untested values pass when smaller ones do: larger heads and lines only read more easily.
    holds = (current["right"] >= ARROWS_PASS if current is not None
             else any(a["arrow_px"] <= arrow and a["line_px"] <= line for a in passing))
    if holds or not arrows:
        pick, why = (arrow, line), "the current arrowheads and lines are read the right way round"
    elif passing:
        best = min(passing, key=lambda a: (a["line_px"], a["arrow_px"]))
        pick, why = (best["arrow_px"], best["line_px"]), f"the smallest read {ARROWS_PASS:.0%} the right way round"
    else:
        best = max(arrows, key=lambda a: a["right"])
        pick, why = (arrow, line), (f"none reaches {ARROWS_PASS:.0%} (the best, {best['right']:.0%}): kept; the "
                                    "diagrams' descriptions may misread arrows whatever their size")
    recs.append(Recommendation("sketch_arrow_px", arrow, pick[0], table, why))
    recs.append(Recommendation("sketch_line_px", line, pick[1], table, why))
    # The modules' size is judged on connections found, either way round: a direction misread is the
    # arrows' measure, and happens among few shapes as among many (plan VC, results).
    large, lo, hi = modules
    dens = summary["density"]
    # Connections can only be harder to find among more shapes: a dip at one size is averaged out.
    fitted = list(zip([d["shapes"] for d in dens], reversed(ec.monotone([d["found"] for d in reversed(dens)])),
                      strict=True))
    table = "connections found among " + ", ".join(f"{d['shapes']} shapes: {d['found']:.0%}" for d in dens)
    ok = [n for n, found in fitted if found >= DENSITY_PASS]
    if not dens or all(found >= DENSITY_PASS for n, found in fitted if n <= hi):
        rec, why = modules, f"connections are found in images of up to {hi} shapes"
    elif ok:
        top = max(ok)
        rec, why = (min(large, top), min(lo, top), top), f"connections are missed among more than {top} shapes"
    else:
        rec, why = modules, "connections are missed even among the fewest shapes: the modules are kept; look at why"
    recs.append(Recommendation("diagram_modules", ":".join(map(str, modules)), ":".join(map(str, rec)), table, why))
    return recs


def changed_settings(recs: list[Recommendation]) -> dict[str, Any]:
    """The tree settings the recommendations change, as the tree stores them."""
    return {r.setting: r.recommended for r in recs if r.changes}


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
    if cost_note:
        lines += ["", cost_note]
    return "\n".join(lines) + "\n"


def save(out_dir: Path, results: list[dict[str, Any]], summary: dict[str, Any], recs: list[Recommendation],
         report: str, cards: list[ec.Card]) -> None:
    (out_dir / "cards").mkdir(parents=True, exist_ok=True)
    for card in cards:
        (out_dir / "cards" / f"{card.id}.png").write_bytes(ec.render(card).png)
    (out_dir / "results.json").write_text(json.dumps(
        {"summary": summary, "recommendations": [r.__dict__ for r in recs], "cards": results},
        indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(report, encoding="utf-8")

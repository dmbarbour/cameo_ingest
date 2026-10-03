"""Calibrating sketches to the configured vision model (plan VC-03, VC-04).

`ask` has the model read eye charts (`eyechart.py`) through the session, so that answers are
stored and a rerun costs nothing; `summarize` fits what it read; `recommend` derives the sketch
settings from the measurements alone. The tree's current values are shown beside them but never
preferred, and no cache is a reason to keep one: a change redraws the sketches, and asks again
for their descriptions, as it should (the maintainer's policy, 2026-10-03).
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
from .sketch import SketchStyle
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
        label: str = "eye charts") -> list[dict[str, Any]]:
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

    with progress.phase(label, len(cards), "card") as ph, ThreadPoolExecutor(max(1, concurrency)) as pool:
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


def measure(llm: EnrichmentSession, name: str, pixels: int, concurrency: int = 4, progress: Progress = QUIET,
            ) -> tuple[list[ec.Card], list[dict[str, Any]]]:
    """A suite's cards and their results, in two stages: the reading cards, then the arrow and
    density cards at the font and budget the reading calls for, so that nothing measured depends
    on the tree's current sizes."""
    first = ec.reading(name, pixels)
    results = ask(llm, first, concurrency, progress, "eye charts: reading")
    chosen = {r.setting: r.recommended for r in _reading(summarize(results), pixels, SKETCH[0])}
    style = SketchStyle(chosen["sketch_font_px"], *SKETCH[1:])
    second = ec.drawings(name, chosen.get("image_pixels", pixels), style)
    return first + second, results + ask(llm, second, concurrency, progress, "eye charts: arrows and density")


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
    if len(flat) == len(reads):
        recs = [Recommendation("image_pixels", pixels, pixels, measured,
                               "the threshold doesn't grow with the image: the model reads at native resolution, "
                               "where more pixels cost more tokens and read no smaller text; the budget is a "
                               "matter of cost, kept as configured")]
        threshold_px = reads.get(1.0) or floor
    else:  # the host shrinks images to a budget of its own: the largest area read as well as the smallest
        areas = sorted(reads)
        held = [a for k, a in enumerate(areas) if all(b in flat for b in areas[:k + 1])]
        best = max(held) if held else max(flat)
        recs = [Recommendation("image_pixels", pixels, _patches(best * pixels), measured,
                               f"text reads as well up to {best:g} times the budget and worse beyond: the host "
                               "shrinks larger images to about that budget")]
        threshold_px = reads[best]
    needed = math.ceil(FONT_MARGIN * threshold_px)
    recs.append(Recommendation("sketch_font_px", font, needed, f"90% read at {threshold_px:g} px",
                               f"{FONT_MARGIN:g} times the threshold (the current size is "
                               f"{font / threshold_px:.2f} times it)"))
    return recs


def recommend(summary: dict[str, Any], pixels: int, sketch: tuple[int, float, int] = SKETCH,
              modules: tuple[int, int, int] = MODULES) -> list[Recommendation]:
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
    else:
        pick = SKETCH[1:]
        top = max((a["right"] for a in arrows), default=0.0)
        why = (f"none reaches {ARROWS_PASS:.0%} (the best, {top:.0%}): the default sizes; descriptions get "
               "every connection's direction as text")
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
               + (" (the most tested)" if top_n == max(n for n, _ in fitted) else ", and missed among more"))
    else:
        rec = MODULES
        why = ("connections are missed even among the fewest shapes: the default modules; look at why"
               if dens else "not measured: the default modules")
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

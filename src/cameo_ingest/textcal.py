"""Reading cards for the text model (plan TC-03): synthetic package text, in the plain form of a
large package's parts (`Section.text`), of a chosen length, with every name and figure invented,
so that what a model reads from each part of an input can be scored exactly.

- **Five groups, one in each fifth of the card.** Each has a hub, a block with a purpose of its
  own ("desalinates seawater for the habitat"), and blocks and requirements that serve it. A
  summary of the card should say what each group is for, wherever it sits. A card of alike
  elements can't test that: its right summary is the pattern, with examples from the start.
- **Elements:** each is named by a word made up for the card (`Varnel Pump`), unique in it, so a
  mention of the word is a mention of the element. A block has a figure (`ratedFlow = 417 L/s`);
  a requirement, an id and a text.
- **Cross-references** stay in their group, so that a name is read where its element is.
- **Two probes on each card:**
  - `summary`: the real `module-summary` request, scored by the groups its answer covers (a hub's
    name or its purpose's keyword), and the elements it names, by fifth;
  - `facts`: five questions, each about a figure in a different fifth, scored right or wrong.

Like the eye charts (`eyechart.py`), cards come from fixed seeds: the same card, the same text.

**The calibration is a guard** (the maintainer's decision, plan TC-05). Parts stay at most 12,000
characters, as measured for summaries; the cards can't show how much larger a strong model's
parts could be. They can show a model that reads 12,000 characters unevenly, or an endpoint that
cuts long inputs, and then parts are made smaller (`calibrate_text`).
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .progress import QUIET, Progress
from .prompts import MODULE_SUMMARY, PART_CHARS, Slot, Template

if TYPE_CHECKING:
    from .llm import EnrichmentSession
    from .state import State

FIFTHS = 5
LENGTHS = (6_000, 12_000, 24_000, 48_000, 96_000)  # characters: 0.5 to 8 times today's part
CARDS = 8  # per length, in a study (scripts/measure_text_reading.py)
GUARD_LENGTHS = (6_000, 12_000, 24_000)  # a calibration's: the default part, half of it, and twice it
GUARD_CARDS = 5  # per length: 30 requests with both probes
SUITE_VERSION = 1  # the cards and rule a text calibration was made with: a new version calibrates again
PASS = 0.9  # groups covered, and facts right, over a length's cards
FLOOR = 0.6  # in every fifth: below it, a fifth is lost, as when an input is cut
SMALLEST = 6_000  # the smallest part size calibration sets
PACKAGE = "Calibration::Reading Card"
SYLLABLES = ("var", "nel", "os", "trin", "ka", "lum", "dre", "vo", "sel", "tam", "ri", "quo", "bra", "zen",
             "mol", "fi", "gar", "pe", "lis", "ton", "har", "ve", "cul", "dax", "mir", "ob", "sta", "nu")
NOUNS = ("Valve", "Pump", "Controller", "Sensor", "Relay", "Manifold", "Gateway", "Actuator", "Filter",
         "Beacon", "Regulator", "Monitor", "Coupler", "Damper", "Inverter", "Feeder")
THEMES = (("desalinates seawater for the habitat", "seawater"), ("stores liquid hydrogen for the launch pad", "hydrogen"),
          ("tracks orbital debris for the observatory", "debris"), ("grows algae for fish feed", "algae"),
          ("cools the reactor loop", "reactor"), ("sorts parcels at the depot", "parcels"),
          ("pumps irrigation water to the vineyard", "vineyard"), ("filters smoke from the kiln", "kiln"),
          ("heats the greenhouse in winter", "greenhouse"), ("charges the tram batteries overnight", "tram"),
          ("lifts grain into the silo", "silo"), ("watches the spillway of the dam", "spillway"))
FIGURES = (("ratedFlow", "L/s", "moves"), ("maxPressure", "kPa", "holds"), ("responseTime", "ms", "answers in"),
           ("operatingTemp", "degC", "runs at"), ("supplyVoltage", "V", "draws"), ("mass", "kg", "weighs"))

FACTS = Template(
    id="text-facts", version=1,
    purpose="Reading card questions for calibrating to the text model (plan TC); scored, not stored.",
    text=("You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
          "Below are questions, then the extracted text of part of a model. Everything in it is invented: "
          "nothing can be guessed, so answer from the text alone. Reply with one line per question, in the form "
          "\"Q1: answer\", giving each figure with its unit, or \"Q1: not stated\" if the text doesn't say.\n\n"
          "{{QUESTIONS}}\n---\n{{SECTIONS}}"),
    slots=(Slot("QUESTIONS", "text", "five numbered questions, each about a figure of one element"),
           Slot("SECTIONS", "text", "the reading card's text: invented blocks and requirements")),
)


@dataclass
class Element:
    word: str  # the invented word that names it, unique in the card
    name: str
    kind: str  # "block" or "requirement"
    text: str
    fact: tuple[str, str] | None = None  # (question, figure), for a block
    attr: str = ""  # the block's figure's attribute
    theme: str = ""  # a hub's purpose's keyword
    start: int = 0  # where its text starts in the card
    fifth: int = 0


@dataclass
class Card:
    length: int
    seed: int
    elements: list[Element] = field(default_factory=list)
    text: str = ""

    @property
    def id(self) -> str:
        return f"text-{self.length}-{self.seed}"


def _words(rng: random.Random, n: int) -> list[str]:
    """`n` distinct invented words of two or three syllables."""
    out: dict[str, None] = {}
    while len(out) < n:
        out[("".join(rng.choice(SYLLABLES) for _ in range(rng.choice((2, 3))))).capitalize()] = None
    return list(out)


def _block(word: str, noun: str, figure: tuple[str, str, str], number: int, purpose: str,
           prev: Element | None) -> Element:
    attr, unit, verb = figure
    value = f"{number} {unit}"
    name = f"{word} {noun}"
    lines = [f"«Block» {name}", "Kind: Class", f"Qualified name: {PACKAGE}::{name}",
             f"Documentation: The {name} {verb} {value} {purpose}."]
    if prev is not None:
        lines += ["Relationships:", f"- Association → {prev.name}"]
    lines += ["Members:", f"- ownedAttribute Property {attr} = {value}"]
    return Element(word, name, "block", "\n".join(lines), (f"What is the {attr} of the {name}?", value), attr)


def _requirement(word: str, number: int, block: Element) -> Element:
    name, rid = f"{word} Limit", f"CAL-{number}"
    lines = [f"«Requirement» {name} ({rid})", "Kind: Class", f"Qualified name: {PACKAGE}::{name}",
             f"Requirement ID: {rid}", f"Requirement text: The {block.name} shall stay within its rated {block.attr}.",
             "Relationships:", f"- Satisfy: {block.name} satisfies this"]
    return Element(word, name, "requirement", "\n".join(lines))


def card(length: int, seed: int) -> Card:
    """A card of about `length` characters (never more), from `seed`: five groups, one a fifth."""
    rng = random.Random(f"{length}:{seed}")
    words = iter(_words(rng, length // 200 + 20))
    numbers = iter(rng.sample(range(100, 1000), 900))  # each figure once, so an answer is exact
    budget = length // FIFTHS - 2
    c = Card(length, seed)
    for theme, keyword in rng.sample(THEMES, FIFTHS):
        hub_word = next(words)
        hub_name = f"{hub_word} Station"
        group: list[Element] = []
        size = 0
        hub = _block(hub_word, "Station", rng.choice(FIGURES), next(numbers),
                     f"in normal service. It {theme}: the blocks around it all serve it, and it sets their duty", None)
        hub.theme = keyword
        size = len(hub.text)
        while True:
            prev = group[-1] if group else None
            if prev is None or prev.kind == "requirement" or rng.random() < 0.6:
                el = _block(next(words), rng.choice(NOUNS), rng.choice(FIGURES), next(numbers),
                            f"for the {hub_name}", prev)
            else:
                el = _requirement(next(words), next(numbers), prev)
            if size + len(el.text) + 2 > budget:
                break
            group.append(el)
            size += len(el.text) + 2
        at = rng.randint(len(group) // 5, len(group) - len(group) // 5) if group else 0  # within the group
        group.insert(at, hub)
        c.elements += group
    size = 0
    for e in c.elements:
        e.start = size + (2 if size else 0)
        size = e.start + len(e.text)
    c.text = "\n\n".join(e.text for e in c.elements)
    for e in c.elements:
        e.fifth = min(FIFTHS - 1, (e.start + len(e.text) // 2) * FIFTHS // len(c.text))
    return c


def cards(lengths: tuple[int, ...] = LENGTHS, per_length: int = CARDS) -> list[Card]:
    return [card(n, seed) for n in lengths for seed in range(per_length)]


def questions(c: Card) -> list[Element]:
    """One block from each fifth, in a shuffled order: the facts probe's questions."""
    rng = random.Random(f"questions:{c.id}")
    picked = [rng.choice([e for e in c.elements if e.fifth == f and e.fact]) for f in range(FIFTHS)]
    rng.shuffle(picked)
    return picked


def facts_values(c: Card) -> dict[str, str]:
    asked = questions(c)
    return {"QUESTIONS": "\n".join(f"Q{i}: {e.fact[0]}" for i, e in enumerate(asked, 1)),  # type: ignore[index]
            "SECTIONS": c.text}


def summary_values(c: Card) -> dict[str, str]:
    """The real part request's values, unlimited: the card is the part, whatever its length."""
    return {"CUT_NOTE": "", "PACKAGE": f"{PACKAGE} {c.seed + 1}", "PART": "2 of 5", "SECTIONS": c.text}


def _mentions(answer: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", answer, re.IGNORECASE) is not None


def score_summary(c: Card, answer: str | None) -> dict[str, Any]:
    """By fifth: the groups the answer covers (its hub named, or its purpose's keyword), of the
    groups there; and the elements it names, of those present."""
    named, present, covered, groups = [0] * FIFTHS, [0] * FIFTHS, [0] * FIFTHS, [0] * FIFTHS
    text = answer or ""
    for e in c.elements:
        present[e.fifth] += 1
        named[e.fifth] += _mentions(text, e.word)
        if e.theme:
            groups[e.fifth] += 1
            covered[e.fifth] += _mentions(text, e.word) or _mentions(text, e.theme)
    return {"covered": covered, "groups": groups, "named": named, "present": present}


_ANSWER = re.compile(r"^\W*Q(\d+)\W*[:.)\-]\s*(.*)$", re.MULTILINE)


def score_facts(c: Card, answer: str | None) -> dict[str, Any]:
    """Each question's figure found in its answer line, by the fifth its element sits in."""
    lines = {int(m.group(1)): m.group(2) for m in _ANSWER.finditer(answer or "")}
    right = [0] * FIFTHS
    posed = [0] * FIFTHS
    for i, e in enumerate(questions(c), 1):
        posed[e.fifth] += 1
        number = e.fact[1].split()[0]  # type: ignore[index]
        right[e.fifth] += re.search(rf"(?<!\d){number}(?!\d)", lines.get(i, "")) is not None
    return {"right": right, "posed": posed}


def ask(llm: EnrichmentSession, cs: list[Card], concurrency: int = 4, progress: Progress = QUIET) -> list[dict[str, Any]]:
    """Both probes on each card, asked through the session's store, and scored."""
    def one(c: Card, probe: str) -> dict[str, Any]:
        # The part request as it was before 0.20.0, which names what it covers, so that coverage can
        # be scored; the request in use says what a part is about, without names (plan GS).
        template, values = ((MODULE_SUMMARY, summary_values(c)) if probe == "summary"
                            else (FACTS, facts_values(c)))
        res = llm.ask(template, values, project="calibration:text", inputs=(f"{c.id}:{probe}",))
        reply = res[0] if res else None
        scored = score_summary(c, reply) if probe == "summary" else score_facts(c, reply)
        return {"card": c.id, "length": c.length, "chars": len(c.text), "elements": len(c.elements),
                "probe": probe, "asked": res is not None, "reply": reply, **scored}

    jobs = [(c, probe) for c in cs for probe in ("summary", "facts")]
    with progress.phase("reading cards", len(jobs), "request") as ph, ThreadPoolExecutor(max(1, concurrency)) as pool:
        futures = [pool.submit(one, c, probe) for c, probe in jobs]
        for done in as_completed(futures):
            done.result()
            ph.advance()
    return [f.result() for f in futures]


def _share(hits: list[int], totals: list[int]) -> list[float | None]:
    return [h / t if t else None for h, t in zip(hits, totals, strict=True)]


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """By length: the summary probe's share of groups covered in each fifth, the middle's rate
    over the ends', and the share of elements named; the facts probe's share right in each fifth,
    and in all."""
    out = []
    for n in sorted({r["length"] for r in results}):
        rs = [r for r in results if r["length"] == n and r["asked"]]
        s = [r for r in rs if r["probe"] == "summary"]
        f = [r for r in rs if r["probe"] == "facts"]
        covered = [sum(r["covered"][k] for r in s) for k in range(FIFTHS)]
        groups = [sum(r["groups"][k] for r in s) for k in range(FIFTHS)]
        named = [sum(r["named"][k] for r in s) for k in range(FIFTHS)]
        present = [sum(r["present"][k] for r in s) for k in range(FIFTHS)]
        right = [sum(r["right"][k] for r in f) for k in range(FIFTHS)]
        posed = [sum(r["posed"][k] for r in f) for k in range(FIFTHS)]
        ends = (covered[0] + covered[-1]) / max(1, groups[0] + groups[-1])
        middle = sum(covered[1:-1]) / max(1, sum(groups[1:-1]))
        out.append({"length": n, "cards": len(s), "covered": _share(covered, groups),
                    "covered_all": sum(covered) / max(1, sum(groups)), "middle_over_ends": middle / ends if ends else None,
                    "named": _share(named, present), "named_all": sum(named) / max(1, sum(present)),
                    "right": _share(right, posed), "right_all": sum(right) / max(1, sum(posed))})
    return out


def passes(row: dict[str, Any]) -> bool:
    """A length read evenly: groups covered and facts right in all, and no fifth lost."""
    fifths = [x for x in row["covered"] + row["right"] if x is not None]
    return bool(row["cards"]) and row["covered_all"] >= PASS and row["right_all"] >= PASS and min(fifths) >= FLOOR


def recommend(summary: list[dict[str, Any]], default: int = PART_CHARS[1]) -> tuple[int, str, str | None]:
    """(part size, why, a warning or None): the default when the model reads it evenly, else the
    smallest; never larger than the default (plan TC-05)."""
    by = {r["length"]: r for r in summary}
    longer = [n for n in sorted(by) if n > default and passes(by[n])]
    if default in by and passes(by[default]):
        beyond = f", and {max(longer):,} too (not used: calibration never makes parts larger)" if longer else ""
        return default, f"reads {default:,}-character inputs evenly{beyond}", None
    if SMALLEST in by and passes(by[SMALLEST]):
        return SMALLEST, f"reads {SMALLEST:,}-character inputs evenly, but not {default:,}", None
    return SMALLEST, f"reads unevenly even at {SMALLEST:,} characters", (
        f"the text model reads unevenly even at {SMALLEST:,} characters: its summaries of large packages may "
        "miss what is far into a part; check the calibration's report")


def problem(results: list[dict[str, Any]]) -> str | None:
    """Why a calibration can't be trusted, or None."""
    missing = sum(not r["asked"] or r["reply"] is None for r in results)
    return f"{missing} of {len(results)} requests went unanswered" if missing else None


@dataclass
class Outcome:
    dest: Path  # the report's directory
    part_chars: int
    why: str
    warning: str | None
    problem: str | None
    settings: dict[str, Any] | None  # as recorded; None when not recorded


def render_report(model: str, endpoint: str | None, summary: list[dict[str, Any]], size: int, why: str,
                  warning: str | None, cost: str) -> str:
    def fifths(xs: list[float | None]) -> str:
        return " · ".join("–" if x is None else f"{x:.0%}" for x in xs)

    lines = [f"# Text calibration: {model}", "",
             f"Endpoint: {endpoint or '(default)'}. Reading cards (`textcal.py`, plan TC): synthetic package text "
             "in five groups, one in each fifth; a summary should cover every group, and five questions ask for a "
             "figure in each fifth. " + cost, "",
             "| Characters | Cards | Groups covered, by fifth | All | Facts right, by fifth | All | Even |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['length']:,} | {r['cards']} | {fifths(r['covered'])} | {r['covered_all']:.0%} | "
              f"{fifths(r['right'])} | {r['right_all']:.0%} | {'yes' if passes(r) else 'no'} |" for r in summary]
    lines += ["", f"**Part size: {size:,} characters.** The model {why}.",
              (f"A length is even when {PASS:.0%} of groups are covered and of facts are right, and no fifth falls "
               f"below {FLOOR:.0%}. The tree's own `--part-chars` wins over this.")]
    if warning:
        lines += ["", f"**Warning:** {warning}."]
    return "\n".join(lines) + "\n"


def recorded(state: State, endpoint: str, model: str) -> dict[str, Any] | None:
    """The settings of a text model's calibration in this tree, if it has one."""
    row = state.calibration(endpoint, model, SUITE_VERSION, "text")
    return json.loads(row["settings"]) if row else None


def calibrate_text(out: Path, state: State, llm: EnrichmentSession, concurrency: int = 1,
                   progress: Progress = QUIET) -> Outcome:
    """The session's text model read on the guard's cards, a report, and the part size recorded
    in the tree when the calibration can be trusted (plan TC-08)."""
    cfg = llm.cfg
    model = cfg.text_model or ""
    results = ask(llm, cards(GUARD_LENGTHS, GUARD_CARDS), concurrency, progress)
    summary = summarize(results)
    size, why, warning = recommend(summary)
    trouble = problem(results)
    stored = llm.outcomes["cached"] + llm.outcomes["replayed"]
    report = render_report(model, cfg.base_url, summary, size, why, warning,
                           f"{len(results)} requests; {stored} answered from the store.")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    dest = out / "calibration" / f"{name}-text-{dt.datetime.now(dt.UTC).date().isoformat()}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "results.json").write_text(json.dumps({"by_length": summary, "requests": results}, indent=1,
                                                  ensure_ascii=False), encoding="utf-8")
    (dest / "report.md").write_text(report, encoding="utf-8")
    settings = None
    if trouble is None:
        settings = {"part_chars": size}
        state.save_calibration(cfg.base_url or "", model, SUITE_VERSION, settings,
                               {"by_length": summary, "why": why, "warning": warning},
                               dest.relative_to(out).as_posix(), kind="text")
    return Outcome(dest, size, why, warning, trouble, settings)

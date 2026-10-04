"""Reading cards for the text model (plan TC-03): synthetic package text, in the plain form of a
large package's parts (`Section.text`), of a chosen length, with every name and figure invented,
so that what a model reads from each part of an input can be scored exactly.

- **Elements:** blocks and requirements. Each is named by a word made up for the card (`Varnel
  Pump`), unique in it, so a mention of the word is a mention of the element. A block has a
  documented purpose and a figure (`ratedFlow = 417 L/s`); a requirement, an id and a text.
- **Cross-references** run only to neighbouring elements, so that a name is read where its
  element is: in the same fifth of the input.
- **Two probes on each card:**
  - `summary`: the real `module-summary` request, scored by the elements its answer names, by
    the fifth of the input each element sits in;
  - `facts`: five questions, each about a figure in a different fifth, scored right or wrong.

Like the eye charts (`eyechart.py`), cards come from fixed seeds: the same card, the same text.
"""

from __future__ import annotations

import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .progress import QUIET, Progress
from .prompts import CURRENT, Slot, Template

if TYPE_CHECKING:
    from .llm import EnrichmentSession

FIFTHS = 5
LENGTHS = (6_000, 12_000, 24_000, 48_000, 96_000)  # characters: 0.5 to 8 times today's part
CARDS = 6  # per length
PACKAGE = "Calibration::Reading Card"
SYLLABLES = ("var", "nel", "os", "trin", "ka", "lum", "dre", "vo", "sel", "tam", "ri", "quo", "bra", "zen",
             "mol", "fi", "gar", "pe", "lis", "ton", "har", "ve", "cul", "dax", "mir", "ob", "sta", "nu")
NOUNS = ("Valve", "Pump", "Controller", "Sensor", "Relay", "Manifold", "Gateway", "Actuator", "Filter",
         "Beacon", "Regulator", "Monitor", "Coupler", "Damper", "Inverter", "Feeder")
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


def card(length: int, seed: int) -> Card:
    """A card of about `length` characters (never more), from `seed`."""
    rng = random.Random(f"{length}:{seed}")
    n = length // 250 + 10  # more words than elements can use
    words = _words(rng, n)
    figures = rng.sample(range(100, 1000), min(n, 900))  # each figure once, so an answer is exact
    c = Card(length, seed)
    size = 0
    for k, word in enumerate(words):
        prev = c.elements[-1] if c.elements else None
        if prev is None or prev.kind == "requirement" or rng.random() < 0.6:
            noun = rng.choice(NOUNS)
            attr, unit, verb = rng.choice(FIGURES)
            figure = f"{figures[k]} {unit}"
            name = f"{word} {noun}"
            lines = [f"«Block» {name}", "Kind: Class", f"Qualified name: {PACKAGE}::{name}",
                     f"Documentation: The {name} {verb} {figure} in normal service."]
            if prev is not None:
                lines += ["Relationships:", f"- Association → {prev.name}"]
            lines += ["Members:", f"- ownedAttribute Property {attr} = {figure}"]
            el = Element(word, name, "block", "\n".join(lines), (f"What is the {attr} of the {name}?", figure), attr)
        else:
            rid = f"CAL-{figures[k]}"
            name = f"{word} Limit"
            lines = [f"«Requirement» {name} ({rid})", "Kind: Class", f"Qualified name: {PACKAGE}::{name}",
                     f"Requirement ID: {rid}",
                     f"Requirement text: The {prev.name} shall stay within its rated {prev.attr}.",
                     "Relationships:", f"- Satisfy: {prev.name} satisfies this"]
            el = Element(word, name, "requirement", "\n".join(lines))
        if size + len(el.text) + 2 > length:
            break
        el.start = size + (2 if size else 0)
        size = el.start + len(el.text)
        c.elements.append(el)
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
    """Elements named in the answer, by fifth: (named, present) for each."""
    named = [0] * FIFTHS
    present = [0] * FIFTHS
    for e in c.elements:
        present[e.fifth] += 1
        named[e.fifth] += bool(answer) and _mentions(answer or "", e.word)
    return {"named": named, "present": present}


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
        template, values = ((CURRENT["module-summary"], summary_values(c)) if probe == "summary"
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
    """By length: the summary probe's share of elements named in each fifth, and the middle's
    rate over the ends'; the facts probe's share right in each fifth, and in all."""
    out = []
    for n in sorted({r["length"] for r in results}):
        rs = [r for r in results if r["length"] == n and r["asked"]]
        s = [r for r in rs if r["probe"] == "summary"]
        f = [r for r in rs if r["probe"] == "facts"]
        named = [sum(r["named"][k] for r in s) for k in range(FIFTHS)]
        present = [sum(r["present"][k] for r in s) for k in range(FIFTHS)]
        right = [sum(r["right"][k] for r in f) for k in range(FIFTHS)]
        posed = [sum(r["posed"][k] for r in f) for k in range(FIFTHS)]
        ends = (named[0] + named[-1]) / max(1, present[0] + present[-1])
        middle = sum(named[1:-1]) / max(1, sum(present[1:-1]))
        out.append({"length": n, "cards": len(s), "named": _share(named, present),
                    "named_all": sum(named) / max(1, sum(present)), "middle_over_ends": middle / ends if ends else None,
                    "right": _share(right, posed), "right_all": sum(right) / max(1, sum(posed))})
    return out

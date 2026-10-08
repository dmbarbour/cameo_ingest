"""Judging topics across models with the panel (plan SB-08c).

A collection's subjects (`topics.subjects`) are gathered into topics by each method; the panel
judges the topics as SB-03 judged subjects:
- **E1, intruder:** five subjects of a topic and one of another, shuffled; the judge names the
  one that doesn't belong. Chance is 1 in 6. A subject is shown by its label, what it holds and
  three of its diagrams, **never its model's name**: topics that are one model each would win on
  the name alone.
- **E3, preference:** two ways of gathering a collection's subjects, as topics with their labels,
  sizes, how many models each spans and example subjects (with their models); asked in both
  orders, ties allowed, a verdict counted only when given in both.

One collection gives one E3 verdict a judge, so the methods are run on several: the whole study
tree, and random subsets of its families (`collections`).

**Measures without judges:** topics, the largest topic's share, and how far topics cut across
models: the share of subjects in a topic that holds subjects of at least two families, and the
mean number of families a topic spans.
"""

from __future__ import annotations

import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..llm import EnrichmentSession
from ..prompts import Slot, Template
from ..topics import Subject, _family
from .subject_judges import _number

SEED = 7
HOLDS_CHARS = 200

_INTRO = ("You help evaluate ways of gathering the subjects of several systems engineering models (UML/SysML, "
          "authored in Cameo) into topics across the models, so that a person can discover what a collection of "
          "models covers, and find what different models hold on the same thing together. ")

INTRUDER = Template(
    id="eval-topics-intruder", version=1,
    purpose="E1 of plan SB-08c: find the subject that a gathering put in another topic.",
    text=(_INTRO + "Below are six subjects, each a group of one model's diagrams. Five were put in the same topic; "
          "one comes from a different topic. Which one is the odd one out?\n\n{{SUBJECTS}}\n\n"
          "Reply with JSON only: {\"odd\": the number of the odd one out, \"reason\": \"one short sentence\"}."),
    slots=(Slot("SUBJECTS", "text", "six subjects, numbered 1 to 6: label, what it holds, three diagrams."),),
)

PREFERENCE = Template(
    id="eval-topics-preference", version=1,
    purpose="E3 of plan SB-08c: prefer one of two gatherings of a collection's subjects into topics.",
    text=(_INTRO + "Below are two ways, A and B, of gathering the {{COUNT}} subjects of {{MODELS}} models into "
          "topics. Each topic is shown by its label, its number of subjects, how many models they come from, and "
          "some example subjects with their models. Which would a systems engineer find more useful? Prefer "
          "topics that each hold one coherent thing, that gather subjects from several models where they are "
          "about the same thing, that differ from each other, and whose labels say what they hold.\n\n"
          "A:\n{{A}}\n\nB:\n{{B}}\n\n"
          "Reply with JSON only: {\"better\": \"A\", \"B\" or \"tie\", \"reason\": \"one short sentence\"}."),
    slots=(Slot("COUNT", "text", "the number of subjects."), Slot("MODELS", "text", "the number of models."),
           Slot("A", "text", "way A: a line a topic."), Slot("B", "text", "way B, likewise.")),
)


def collections(subs: list[Subject], n: int = 9, share: float = 0.6) -> list[dict[str, Any]]:
    """The whole collection, then n random subsets of its families, each `share` of them."""
    fams = sorted({_family(s) for s in subs})
    out = [{"name": "all", "subjects": list(subs)}]
    for i in range(n):
        rng = random.Random(f"{SEED}:collection:{i}")
        keep = set(rng.sample(fams, max(2, round(share * len(fams)))))
        out.append({"name": f"subset-{i + 1}", "subjects": [s for s in subs if _family(s) in keep]})
    return out


def as_split(view: dict[str, Any]) -> dict[str, Any]:
    """A topics view as {"labels": {t: label}, "groups": {t: [subject ids]}, "unsorted": [...]}."""
    return {"labels": {str(t): v["label"] for t, v in enumerate(view["topics"])},
            "groups": {str(t): list(v["subjects"]) for t, v in enumerate(view["topics"])},
            "unsorted": list(view.get("unsorted") or [])}


def measures(split: dict[str, Any], by_id: dict[str, Subject]) -> dict[str, Any]:
    sizes = {t: len(ids) for t, ids in split["groups"].items()}
    total = sum(sizes.values()) or 1
    spans = {t: len({_family(by_id[i]) for i in ids}) for t, ids in split["groups"].items()}
    return {"topics": len(sizes), "largest": max(sizes.values(), default=0) / total,
            "across": sum(sizes[t] for t in sizes if spans[t] > 1) / total,
            "families_per_topic": sum(spans.values()) / max(1, len(spans)), "unsorted": len(split["unsorted"])}


def describe(s: Subject, model: bool = False) -> str:
    holds = s.holds[:HOLDS_CHARS] + ("…" if len(s.holds) > HOLDS_CHARS else "")
    shown = "; ".join(s.titles[:3])
    return (s.label + (f" ({s.model})" if model else "") + (f": {holds}" if holds else "")
            + (f" Diagrams such as: {shown}" if shown else ""))


def intruder_tasks(coll: str, split_name: str, split: dict[str, Any], trials: int = 3) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}:{coll}:{split_name}")
    groups = split["groups"]
    out = []
    for t, members in sorted(groups.items()):
        others = [i for u, ms in groups.items() if u != t for i in ms]
        if len(members) < 5 or not others:
            continue
        for n in range(trials):
            five, odd = rng.sample(sorted(members), 5), rng.choice(sorted(others))
            shown = five + [odd]
            rng.shuffle(shown)
            out.append({"test": "E1", "collection": coll, "split": split_name, "group": t, "trial": n,
                        "ids": shown, "answer": shown.index(odd) + 1})
    return out


def preference_tasks(coll: str, names: list[str]) -> list[dict[str, Any]]:
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for first, second in ((a, b), (b, a)):
                out.append({"test": "E3", "collection": coll, "pair": f"{a}-{b}", "A": first, "B": second})
    return out


def show(split: dict[str, Any], by_id: dict[str, Subject]) -> str:
    lines = []
    for t, ids in sorted(split["groups"].items(), key=lambda kv: -len(kv[1])):
        models = len({_family(by_id[i]) for i in ids})
        examples = "; ".join(f"{by_id[i].label} ({by_id[i].model})" for i in ids[:: max(1, len(ids) // 4)][:4])
        lines.append(f"- {split['labels'][t]} ({len(ids)} subjects, {models} model{'s' if models > 1 else ''}), "
                     f"e.g. {examples}")
    if split["unsorted"]:
        lines.append(f"- Not sorted yet ({len(split['unsorted'])} subjects)")
    return "\n".join(lines)


def run(llm: EnrichmentSession, colls: dict[str, dict[str, Any]], tasks: list[dict[str, Any]],
        concurrency: int = 8) -> list[dict[str, Any]]:
    """Ask each task: E1 adds "correct", E3 "better" (the split preferred, "tie", or None)."""

    def one(t: dict[str, Any]) -> dict[str, Any]:
        c = colls[t["collection"]]
        by_id = c["by_id"]
        if t["test"] == "E1":
            text = "\n".join(f"{n}. {describe(by_id[i])}" for n, i in enumerate(t["ids"], 1))
            res = llm.ask(INTRUDER, {"SUBJECTS": text}, project="study:topics", inputs=(t["collection"],))
            got = _number(res[0], "odd") if res else None
            return {**t, "reply": got, "correct": str(got) == str(t["answer"]) if got is not None else None}
        models = len({_family(s) for s in c["subjects"]})
        res = llm.ask(PREFERENCE, {"COUNT": str(len(c["subjects"])), "MODELS": str(models),
                                   "A": show(c["splits"][t["A"]], by_id), "B": show(c["splits"][t["B"]], by_id)},
                      project="study:topics", inputs=(t["collection"],))
        got = str(_number(res[0], "better") or "").strip().upper() if res else ""
        return {**t, "reply": got or None, "better": {"A": t["A"], "B": t["B"], "TIE": "tie"}.get(got)}

    with ThreadPoolExecutor(concurrency) as pool:
        return list(pool.map(one, tasks))


def verdicts(rows: list[dict[str, Any]]) -> Counter[str]:
    """E3: each judge and collection's verdict when given in both orders, else "inconsistent"."""
    both: dict[tuple[str, str, str], list[Any]] = {}
    for r in rows:
        both.setdefault((r["judge"], r["collection"], r["pair"]), []).append(r["better"])
    return Counter(v[0] if len(v) == 2 and v[0] == v[1] and v[0] else "inconsistent" for v in both.values())

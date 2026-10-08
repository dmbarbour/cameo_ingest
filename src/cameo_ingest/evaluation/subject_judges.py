"""Judging splits into subjects with a panel of models (plan SB-03).

- **E1, intruder:** five members of a group and one of another group of the same family,
  shuffled; the judge names the one that doesn't belong. Chance is 1 in 6.
- **E2, label fit:** a diagram and the split's labels, shuffled; the judge says which subject it
  is in. Scored against the split, and corrected for chance (1 in the number of groups). The
  labels are made without the diagrams E2 asks about (`labels_heldout`): a label made from a
  diagram's own words gives it away, which let random splits score 0.17 over chance.
- **E3, preference:** two splits of a family, as labels, sizes and three example names a group;
  asked in both orders, ties allowed. A verdict counts only when a judge gives it in both orders:
  two of the three judges chose the split shown first about 76% of the time.

A diagram is shown by its name, its kind and its about text, **never its package path**: the
package split would win E1 and E2 on the path alone. E3 shows each split as its labels, and a
package split's labels are package names, as a user would see them.

Answers go through `EnrichmentSession`, so they are cached and logged, as other judges' are.
"""

from __future__ import annotations

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..llm import EnrichmentSession
from ..prompts import Slot, Template

SEED = 7
ABOUT_CHARS = 300

_INTRO = ("You help evaluate ways of organizing the diagrams of systems engineering models (UML/SysML, "
          "authored in Cameo) into subjects, so that a person can discover what a model covers. ")

INTRUDER = Template(
    id="eval-subjects-intruder", version=1,
    purpose="E1 of plan SB: find the diagram that a split put in another group.",
    text=(_INTRO + "Below are six diagrams from one model. Five were put in the same subject; one comes from a "
          "different subject. Which one is the odd one out?\n\n{{DIAGRAMS}}\n\n"
          "Reply with JSON only: {\"odd\": the number of the odd one out, \"reason\": \"one short sentence\"}."),
    slots=(Slot("DIAGRAMS", "text", "six diagrams, numbered 1 to 6: name, kind, and what it is about."),),
)

LABEL_FIT = Template(
    id="eval-subjects-label-fit", version=1,
    purpose="E2 of plan SB: put one diagram in one of a split's labelled subjects.",
    text=(_INTRO + "A model's diagrams were organized into the subjects listed below. Which subject does this "
          "diagram belong to?\n\nSubjects:\n{{SUBJECTS}}\n\nDiagram:\n{{DIAGRAM}}\n\n"
          "Reply with JSON only: {\"subject\": the number of the subject, \"reason\": \"one short sentence\"}."),
    slots=(Slot("SUBJECTS", "text", "the split's labels, numbered."),
           Slot("DIAGRAM", "text", "the diagram: name, kind, and what it is about.")),
)

PREFERENCE = Template(
    id="eval-subjects-preference", version=1,
    purpose="E3 of plan SB: prefer one of two splits of a model.",
    text=(_INTRO + "Below are two ways, A and B, of organizing the {{COUNT}} diagrams of one model, named "
          "{{MODEL}}. Each subject is shown by its label, its number of diagrams and some example diagram names. "
          "Which would a systems engineer find more natural for discovering the different things this model "
          "covers? Prefer subjects that each hold one coherent topic, that differ from each other, and whose "
          "labels say what they hold.\n\nA:\n{{A}}\n\nB:\n{{B}}\n\n"
          "Reply with JSON only: {\"better\": \"A\", \"B\" or \"tie\", \"reason\": \"one short sentence\"}."),
    slots=(Slot("COUNT", "text", "the number of diagrams."), Slot("MODEL", "text", "the model's name."),
           Slot("A", "text", "split A: a line a subject."), Slot("B", "text", "split B, likewise.")),
)


def describe(item: dict[str, Any]) -> str:
    about = (item.get("about") or "").replace("\n", " ")
    about = about[:ABOUT_CHARS] + ("…" if len(about) > ABOUT_CHARS else "")
    title = (item["name"] or "(unnamed)") + (f", of {item['owner']}" if item.get("owner") else "")
    return f"{title} ({item['kind']})" + (f": {about}" if about else "")


def pick(recs: list[dict], n: int) -> list[dict]:
    """The n families to judge: sizes spread from the largest down."""
    by_size = sorted(recs, key=lambda r: -len(r["items"]))
    if len(by_size) <= n:
        return by_size
    step = len(by_size) / n
    return [by_size[int(i * step)] for i in range(n)]


def intruder_tasks(rec: dict[str, Any], split: str, trials: int = 3) -> list[dict[str, Any]]:
    """E1 tasks for one family's split: `trials` a group of at least 5, each with an intruder from
    another group."""
    rng = random.Random(f"{SEED}:{rec['family']}:{split}")
    groups = rec["splits"][split]["groups"]
    out = []
    for g, members in sorted(groups.items()):
        others = [k for h, ms in groups.items() if h != g for k in ms]
        if len(members) < 5 or not others:
            continue
        for t in range(trials):
            five, odd = rng.sample(sorted(members), 5), rng.choice(sorted(others))
            shown = five + [odd]
            rng.shuffle(shown)
            out.append({"test": "E1", "family": rec["family"], "split": split, "group": g, "trial": t,
                        "keys": shown, "answer": shown.index(odd) + 1})
    return out


def label_tasks(rec: dict[str, Any], split: str, n: int = 20) -> list[dict[str, Any]]:
    """E2 tasks for one family's split: n diagrams, each with the split's labels, shuffled."""
    rng = random.Random(f"{SEED}:{rec['family']}:{split}:labels")
    s = rec["splits"][split]
    where = {k: g for g, ms in s["groups"].items() for k in ms}
    keys = rec["e2_sample"][:n]
    out = []
    for k in keys:
        order = sorted(s["labels"])
        rng.shuffle(order)
        out.append({"test": "E2", "family": rec["family"], "split": split, "key": k, "order": order,
                    "answer": order.index(where[k]) + 1, "groups": len(order)})
    return out


def preference_tasks(rec: dict[str, Any], splits: list[str]) -> list[dict[str, Any]]:
    """E3 tasks: every pair of splits, in both orders."""
    out = []
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            for first, second in ((a, b), (b, a)):
                out.append({"test": "E3", "family": rec["family"], "pair": f"{a}-{b}", "A": first, "B": second})
    return out


def _show_split(rec: dict[str, Any], split: str) -> str:
    s = rec["splits"][split]
    lines = []
    for g, members in sorted(s["groups"].items(), key=lambda kv: -len(kv[1])):
        examples = "; ".join(rec["items"][k]["name"] + (f", of {rec['items'][k]['owner']}" if rec["items"][k].get("owner")
                                                         else "") for k in sorted(members)[:3])
        lines.append(f"- {s['labels'][g]} ({len(members)} diagrams), e.g. {examples}")
    return "\n".join(lines)


def reply_field(reply: str, key: str) -> Any:
    """A field of a judge's JSON reply, read leniently: from the JSON, else by pattern."""
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        return json.loads(m.group(0)).get(key) if m else None
    except json.JSONDecodeError:
        g = re.search(rf'"{key}"\s*:\s*"?([A-Za-z0-9]+)', reply)
        return g.group(1) if g else None


def run(llm: EnrichmentSession, recs: dict[str, dict[str, Any]], tasks: list[dict[str, Any]],
        concurrency: int = 8) -> list[dict[str, Any]]:
    """Ask each task; the result adds "reply" (what was read, or None) and "correct" (E1, E2) or
    "better" (E3: the split preferred, "tie", or None)."""

    def one(t: dict[str, Any]) -> dict[str, Any]:
        rec = recs[t["family"]]
        if t["test"] == "E1":
            text = "\n".join(f"{i}. {describe(rec['items'][k])}" for i, k in enumerate(t["keys"], 1))
            res = llm.ask(INTRUDER, {"DIAGRAMS": text}, project="study:subjects", inputs=(t["family"],))
            got = reply_field(res[0], "odd") if res else None
            return {**t, "reply": got, "correct": str(got) == str(t["answer"]) if got is not None else None}
        if t["test"] == "E2":
            labels = rec["splits"][t["split"]]["labels_heldout"]
            subjects = "\n".join(f"{i}. {labels[g]}" for i, g in enumerate(t["order"], 1))
            res = llm.ask(LABEL_FIT, {"SUBJECTS": subjects, "DIAGRAM": describe(rec["items"][t["key"]])},
                          project="study:subjects", inputs=(t["family"],))
            got = reply_field(res[0], "subject") if res else None
            return {**t, "reply": got, "correct": str(got) == str(t["answer"]) if got is not None else None}
        res = llm.ask(PREFERENCE, {"COUNT": str(len(rec["items"])), "MODEL": rec["family"],
                                   "A": _show_split(rec, t["A"]), "B": _show_split(rec, t["B"])},
                      project="study:subjects", inputs=(t["family"],))
        got = str(reply_field(res[0], "better") or "").strip().upper() if res else ""
        better = {"A": t["A"], "B": t["B"], "TIE": "tie"}.get(got)
        return {**t, "reply": got or None, "better": better}

    with ThreadPoolExecutor(concurrency) as pool:
        return list(pool.map(one, tasks))

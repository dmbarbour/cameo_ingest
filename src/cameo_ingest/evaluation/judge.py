"""Relevance judgments by a panel of models, for pooled search results (plan RE-06).

A judge reads a question and one retrieved passage (a window of a chunk, links reduced to their
labels) and grades it: 2 if it contains the answer, 1 if it is about the subject and helps
without answering, 0 otherwise. Answers go through `LLM`, so they are cached and logged.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..llm import EnrichmentSession
from ..plain import plain
from ..prompts import Slot, Template

JUDGE = Template(
    id="eval-relevance-judge",
    version=1,
    purpose="Grades one search result for one question, for the retrieval evaluation (plan RE-06).",
    text=(
        "You judge search results for questions about systems engineering models (UML/SysML, authored in "
        "Cameo). The index holds many unrelated models. Below is a question and one result: a passage of a "
        "model's documentation, or a generated summary of part of it. Grade how well the passage serves the "
        "question:\n"
        "2: it contains the information that answers the question, fully or in its main part;\n"
        "1: it is about the question's subject and would help, but does not answer it;\n"
        "0: it does not help. A passage about a different model or element that merely shares words with the "
        "question is 0.\n\n"
        "Reply with JSON only: {\"grade\": 0, 1 or 2, \"reason\": \"one short sentence\"}.\n\n"
        "Question: {{QUESTION}}\n---\nPassage:\n{{PASSAGE}}"
    ),
    slots=(
        Slot("QUESTION", "text", "the question, as the evaluation asks it."),
        Slot("PASSAGE", "text", "the retrieved window, with links reduced to their labels and the trace line "
                                "dropped, cut at 4,000 characters."),
    ),
)

_GRADE = re.compile(r'"grade"\s*:\s*([012])')


def judge(llm: EnrichmentSession, pairs: list[dict], concurrency: int = 16) -> list[dict]:
    """Grade each pair ({"question", "text", ...}); the result adds "grade" (None if the reply
    can't be read) and "reason"."""

    def one(p: dict) -> dict:
        res = llm.ask(JUDGE, {"QUESTION": p["question"], "PASSAGE": plain(p["text"])[:4000]},
                      project="study:retrieval-judging", inputs=(p.get("unit", ""),))
        grade, reason = None, ""
        if res is not None:
            m = re.search(r"\{.*\}", res[0], re.DOTALL)
            try:
                reply = json.loads(m.group(0)) if m else {}
                grade = int(reply["grade"]) if str(reply.get("grade")) in ("0", "1", "2") else None
                reason = str(reply.get("reason", ""))[:300]
            except (json.JSONDecodeError, KeyError, ValueError):
                g = _GRADE.search(res[0])  # a reply that isn't clean JSON
                grade = int(g.group(1)) if g else None
        return {**{k: v for k, v in p.items() if k != "text"}, "grade": grade, "reason": reason}

    with ThreadPoolExecutor(concurrency) as pool:
        return list(pool.map(one, pairs))


def kappa(a: list[int], b: list[int], categories: tuple[int, ...] = (0, 1, 2)) -> float:
    """Cohen's kappa for two raters' grades of the same items."""
    n = len(a)
    if not n:
        return 0.0
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in categories)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def consensus(judgments: list[dict], main: tuple[str, str], tiebreak: str | None = None) -> dict[tuple, int]:
    """The panel's grade per (set, question, unit): the two main judges' when they agree; else the
    tie-breaker's, or without one, the lower of theirs. A pair judged by one main judge only
    takes that judge's grade."""
    by_pair: dict[tuple, dict[str, int]] = {}
    for j in judgments:
        if j.get("grade") is not None:
            by_pair.setdefault((j["set"], j["qid"], j["unit"]), {})[j["judge"]] = j["grade"]
    out = {}
    for key, g in by_pair.items():
        a, b = g.get(main[0]), g.get(main[1])
        if a is not None and b is not None:
            out[key] = a if a == b else g.get(tiebreak, min(a, b)) if tiebreak else min(a, b)
        elif a is not None or b is not None:
            out[key] = a if a is not None else b  # type: ignore[assignment]
    return out


def panel(judgments: list[dict], set_name: str, main: tuple[str, str], tiebreak: str | None = None,
          ) -> dict[str, dict[str, int]]:
    """The panel's grades (`consensus`) for one question set, by question id and window id."""
    out: dict[str, dict[str, int]] = {}
    for (s, qid, unit), grade in consensus(judgments, main, tiebreak).items():
        if s == set_name:
            out.setdefault(qid, {})[unit] = grade
    return out


# The panel of plan SB (subjects and topics): three judges from different makers.
PANEL = ["deepseek-ai/DeepSeek-V3.2", "Qwen/Qwen3-235B-A22B-Instruct-2507", "openai/gpt-oss-120b"]


def kappa_lines(rows: list[dict], judges: list[str], key: Any) -> list[str]:
    """Markdown lines: each pair of judges' kappa on the tasks both answered (`correct` not None),
    tasks matched by `key(row)`."""
    lines = []
    for i, a in enumerate(judges):
        for b in judges[i + 1:]:
            pa = {key(r): r["correct"] for r in rows if r["judge"] == a and r["correct"] is not None}
            pb = {key(r): r["correct"] for r in rows if r["judge"] == b and r["correct"] is not None}
            common = sorted(set(pa) & set(pb))
            k = kappa([int(pa[c]) for c in common], [int(pb[c]) for c in common], (0, 1)) if common else float("nan")
            lines.append(f"- {a.split('/')[-1]} and {b.split('/')[-1]}: {k:.2f} on {len(common)} tasks")
    return lines


def both_orders(rows: list[dict], unit: Any) -> Counter:
    """Preferences asked in both orders: each unit's (`unit(row)`) verdict when the same both
    times, else "inconsistent" (a judge that prefers whatever is shown first)."""
    both: dict[Any, list[Any]] = {}
    for r in rows:
        both.setdefault(unit(r), []).append(r["better"])
    return Counter(v[0] if len(v) == 2 and v[0] == v[1] and v[0] else "inconsistent" for v in both.values())


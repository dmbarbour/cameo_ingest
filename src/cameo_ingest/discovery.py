"""What subjects (`subjects`, ADR-0031) and topics across models (`topics`) share, and the file
they are kept in (review CQ-007, CQ-008).

- **Asking:** a request whose replay miss counts as unanswered (`asker`), a reply's JSON
  (`reply_json`), numbered answers placed in groups or left unsorted (`place`), and how a
  family's or the tree's answers stand (`status`). Never a guess: what isn't placed stays under
  `UNSORTED`, and the next run asks again.
- **Without the LLM:** Louvain communities the same whatever the hash seed (`louvain`), merged
  down to a target (`merge_down`), labelled by their distinctive words (`distinctive`).
- **The file,** `subjects.json` at the tree's root: `format`, the families' records, then the
  topics'. A topic names a subject as `token/n`: its family's newest token, and its place in the
  family's default view (`subject_ref`, `split_ref`, `default_view`).
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any

import networkx as nx

from .llm import ReplayMiss

log = logging.getLogger(__name__)

FILE = "subjects.json"
FORMAT = 1
SEED = 1
UNSORTED = "Not sorted yet"
UNSORTED_NOTE = "The LLM gave no answer for these; the next run asks again."
UNSORTED_LIMIT = 0.05  # more unsorted than this, and the fallback is the default view

WORD = re.compile(r"[a-z][a-z0-9]+")
STOP = frozenset("""a an and are as at be by for from has have in into is it its of on or that the this to with
which what how each their they these those diagram model package shows show showing describes defines""".split())  # noqa: SIM905

def tokens(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def target(n: int) -> int:
    """How many groups n things are split into: about the square root of n/2, 2 to 15."""
    return max(2, min(15, round(math.sqrt(n / 2))))


# -- asking ------------------------------------------------------------------------------------------
def reply_json(reply: Any) -> Any:
    """The JSON object in a reply (or a (text, ...) answer), or None."""
    text = reply[0] if isinstance(reply, tuple) else reply
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def asker(llm: Any, project: str, inputs: tuple[str, ...]) -> Callable[[Any, dict[str, str]], Any]:
    """`llm.ask` for requests logged under `project` and `inputs`; in a replayed run, a miss at the
    root is an unanswered request, not a failure."""
    def ask(template: Any, values: dict[str, str]) -> Any:
        try:
            return llm.ask(template, values, project=project, inputs=inputs)
        except ReplayMiss as e:
            log.debug("%s: %s", project, e)
            return None
    return ask


def place[K: Hashable](answers: dict[K, Any], groups: int) -> tuple[dict[int, list[K]], list[K]]:
    """Answers, each a group's number from 1 (or anything else), as (members by group from 0,
    the unsorted), each in the keys' order."""
    members: dict[int, list[K]] = {}
    unsorted: list[K] = []
    for key, v in sorted(answers.items()):
        try:
            g = int(v) - 1
        except (TypeError, ValueError):
            g = -1
        if 0 <= g < groups:
            members.setdefault(g, []).append(key)
        else:
            unsorted.append(key)
    return members, unsorted


def status(found: bool, complete: bool, asked: bool) -> str:
    """How a family's ways, or the topics, stand: `found`, `incomplete`, `failed` or `not asked`."""
    return "found" if found and complete else "incomplete" if found else "failed" if asked else "not asked"


# -- without the LLM ---------------------------------------------------------------------------------
def louvain(g: nx.Graph) -> list[set[Any]]:
    """Louvain communities, the same whatever the hash seed: networkx gathers nodes in sets, whose
    order for strings depends on it, so the nodes go in as numbers, in sorted order."""
    names = sorted(g.nodes)
    num = nx.Graph()
    num.add_nodes_from(range(len(names)))
    index = {n: i for i, n in enumerate(names)}
    num.add_weighted_edges_from(sorted((min(index[a], index[b]), max(index[a], index[b]), d["weight"])
                                       for a, b, d in g.edges(data=True)))
    return [{names[i] for i in c} for c in nx.community.louvain_communities(num, weight="weight", seed=SEED)]


def merge_down[K: Hashable](communities: list[set[K]], k: int, into: Callable[[int, dict[int, set[K]], dict[K, int]], int],
               least: int = 1) -> dict[K, int]:
    """Communities merged, the smallest first (the one with the least member, on a tie), into the
    group `into(small, members, group)` chooses, until at most k are left and none is smaller than
    `least`; then numbered, largest first. Item -> group."""
    members = dict(enumerate(communities))
    group = {x: i for i, c in members.items() for x in c}
    while len(members) > 1 and (len(members) > k or min(len(c) for c in members.values()) < least):
        small = min(members, key=lambda i: (len(members[i]), min(members[i])))
        dest = into(small, members, group)
        for x in members.pop(small):
            group[x] = dest
            members[dest].add(x)
    order = {i: n for n, i in enumerate(sorted(members, key=lambda i: (-len(members[i]), min(members[i]))))}
    return {x: order[i] for x, i in group.items()}


def distinctive[K: Hashable](split: dict[K, int], words: Callable[[K], set[str]], group: int, n: int = 3,
                common: frozenset[str] | set[str] = frozenset()) -> str:
    """A group's distinctive words: frequent in it, rare outside, leaving out `common` ones; a word
    once in a group of several doesn't count."""
    inside: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    for key, g in split.items():
        (inside if g == group else outside).update(words(key))
    size = sum(1 for g in split.values() if g == group)
    rest = max(1, len(split) - size)
    score = {w: c / size - outside[w] / rest for w, c in inside.items() if (c > 1 or size == 1) and w not in common}
    return ", ".join(w for w, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:n]) or "(no distinctive words)"


# -- the file ----------------------------------------------------------------------------------------
def read(out: Path) -> dict[str, Any] | None:
    """The tree's `subjects.json`, if there is one of this format."""
    try:
        data = json.loads((out / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("format") == FORMAT else None


def write(out: Path, families: list[dict[str, Any]], topics: dict[str, Any]) -> None:
    data = {"format": FORMAT, "families": families, "topics": topics}
    tmp = out / (FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(out / FILE)


def default_view(rec: dict[str, Any]) -> dict[str, Any]:
    """A family's (or the topics') default view."""
    return next(v for v in rec["views"] if v["id"] == rec["default"])


def subject_ref(token: str, n: int) -> str:
    """How a topic names a subject: its family's newest token, and its place in the default view."""
    return f"{token}/{n}"


def split_ref(ref: str) -> tuple[str, int]:
    token, _, n = ref.rpartition("/")
    return token, int(n)

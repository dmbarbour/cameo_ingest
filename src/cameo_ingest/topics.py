"""Topics across models (plan SB CP4): every family's subjects, in its suggested view, gathered
into topics that span the collection, so that a person can find what different models hold on
the same thing together.

- **A subject** is one of a family's subjects in its default view (`subjects.json`); unsorted
  diagrams aren't one. It is read by its label, what it holds, and its diagrams' names and about
  texts; it shows the elements its diagrams show.
- **Words,** without the LLM: subjects joined by their words (TF-IDF, each joined to its `NEAR`
  nearest) and, between families, by the elements they both show; Louvain communities, merged
  down to about the square root of half the subjects; labelled by their distinctive words.
- **The LLM:** the tree's text model proposes about that many topics from the list of every
  subject, then puts each subject in one, `BATCH` subjects a request. Subjects it couldn't place
  stay under "Not sorted yet".
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from .llm import ReplayMiss
from .prompts import TOPICS_ASSIGN, TOPICS_PROPOSE
from .subjects import UNSORTED_LIMIT, Family, _json, _tokens, louvain, target

log = logging.getLogger(__name__)

NEAR = 5  # each subject joined to its nearest by words
SHARED_WEIGHT = 1.0  # sharing all its elements counts as much as the same words
BATCH = 30  # subjects an assignment request
LISTED = 400  # subjects in a proposal's list, at most
HOLDS_CHARS = 160
EXAMPLES = 3  # diagrams shown with a subject


@dataclass
class Subject:
    id: str  # the family's newest token, then the subject's place in its default view: "sha256:…/3"
    model: str  # the family's name
    label: str
    holds: str
    diagrams: list[str]
    titles: list[str]  # its diagrams' titles, in order
    text: str  # label, holds, titles and about texts: what its words are read from
    elements: set[str] = field(default_factory=set)

    @property
    def family(self) -> str:
        """Its family's newest token."""
        return self.id.rpartition("/")[0]

    def describe(self, examples: int = EXAMPLES) -> str:
        holds = self.holds[:HOLDS_CHARS] + ("…" if len(self.holds) > HOLDS_CHARS else "")
        shown = "; ".join(self.titles[:examples])
        return (f"{self.label} ({self.model}, {len(self.diagrams)} diagrams)" + (f": {holds}" if holds else "")
                + (f" e.g. {shown}" if shown else ""))


def default_view(rec: dict[str, Any]) -> dict[str, Any]:
    return next(v for v in rec["views"] if v["id"] == rec["default"])


def subjects(fams: list[Family], recs: dict[str, dict[str, Any]]) -> list[Subject]:
    """The families' subjects in their default views, in the families' order."""
    out = []
    for f in fams:
        rec = recs.get(f.tokens[0])
        if rec is None:
            continue
        for n, s in enumerate(default_view(rec)["subjects"]):
            keys = [k for k in s["diagrams"] if k in f.items]
            if not keys:
                continue
            its = [f.items[k] for k in keys]
            out.append(Subject(f"{f.tokens[0]}/{n}", f.name, s["label"], s.get("holds") or "", keys,
                               [it.title for it in its],
                               " ".join([s["label"], s.get("holds") or ""] + [it.title + " " + it.about for it in its]),
                               set().union(*(it.shows for it in its))))
    return out


def signature(subs: list[Subject]) -> str:
    h = hashlib.sha256()
    for s in subs:
        h.update(f"\0{s.id}\0{s.label}\0{s.holds}\0{len(s.diagrams)}".encode())
    return h.hexdigest()[:16]


# -- words and shared elements: the fallback ---------------------------------------------------------
def similarity(subs: list[Subject]) -> dict[tuple[int, int], float]:
    """Cosine of the subjects' TF-IDF vectors, between subjects of different families: a model's
    own words (in no other family's subjects) would join its subjects to each other, and topics
    would be models again; words in more than half the subjects are left out too."""
    docs = [Counter(_tokens(s.text)) for s in subs]
    n = len(subs)
    df = Counter(w for d in docs for w in d)
    spread: dict[str, set[str]] = defaultdict(set)
    for s, d in zip(subs, docs, strict=True):
        for w in d:
            spread[w].add(s.family)
    idf = {w: math.log(n / c) for w, c in df.items() if c <= max(1, n / 2) and len(spread[w]) > 1}
    vecs = []
    for d in docs:
        v = {w: (1 + math.log(c)) * idf[w] for w, c in d.items() if w in idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    having: dict[str, list[int]] = defaultdict(list)
    for i, v in enumerate(vecs):
        for w in sorted(v):
            having[w].append(i)
    sim: dict[tuple[int, int], float] = defaultdict(float)
    for w, ids in sorted(having.items()):
        for x, i in enumerate(ids):
            for j in ids[x + 1:]:
                if subs[i].family != subs[j].family:
                    sim[i, j] += vecs[i][w] * vecs[j][w]
    return dict(sim)


def shared(subs: list[Subject]) -> dict[tuple[int, int], float]:
    """Between subjects of different families: the elements both show, over the fewer either shows."""
    by_element: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(subs):
        for e in sorted(s.elements):
            by_element[e].append(i)
    both: Counter[tuple[int, int]] = Counter()
    for _, ids in sorted(by_element.items()):
        for x, i in enumerate(ids):
            for j in ids[x + 1:]:
                if subs[i].family != subs[j].family:
                    both[i, j] += 1
    return {(i, j): c / min(len(subs[i].elements), len(subs[j].elements)) for (i, j), c in both.items()}


def graph(subs: list[Subject]) -> tuple[nx.Graph, dict[tuple[int, int], float]]:
    """Each subject joined to its `NEAR` nearest by words, and to every subject of another family
    it shares elements with; also every pair's joined weight, for merging."""
    sim = similarity(subs)
    links = shared(subs)
    weight: dict[tuple[int, int], float] = defaultdict(float)
    for pair, x in sim.items():
        weight[pair] += x
    for pair, x in links.items():
        weight[pair] += SHARED_WEIGHT * x
    near: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for (i, j), x in sim.items():
        near[i].append((x, j))
        near[j].append((x, i))
    keep = set(links)
    for i, xs in near.items():
        for _, j in sorted(xs, key=lambda t: (-t[0], t[1]))[:NEAR]:
            keep.add((min(i, j), max(i, j)))
    g = nx.Graph()
    g.add_nodes_from(range(len(subs)))
    g.add_weighted_edges_from((i, j, weight[i, j]) for i, j in sorted(keep) if weight[i, j] > 0)
    return g, dict(weight)


def split_words(subs: list[Subject], k: int | None = None) -> dict[int, int]:
    """Subject index -> topic: Louvain communities of `graph`, the smallest merged into the one
    it is most joined to (by every pair's weight) until k are left."""
    k = k or target(len(subs))
    g, weight = graph(subs)
    named = nx.relabel_nodes(g, {i: f"{i:06d}" for i in g.nodes})
    comms = [{int(x) for x in c} for c in louvain(named)]
    members = dict(enumerate(comms))
    group = {i: n for n, c in members.items() for i in c}
    while len(members) > max(1, k):
        small = min(members, key=lambda n: (len(members[n]), min(members[n])))
        ties: Counter[int] = Counter()
        for i in members[small]:
            for j in range(len(subs)):
                if group[j] != small:
                    ties[group[j]] += weight.get((min(i, j), max(i, j)), 0.0)
        into = max((n for n in members if n != small), key=lambda n: (ties[n], len(members[n]), -n))
        for i in members.pop(small):
            group[i] = into
            members[into].add(i)
    order = {n: r for r, n in enumerate(sorted(members, key=lambda n: (-len(members[n]), min(members[n]))))}
    return {i: order[n] for i, n in group.items()}


def word_label(subs: list[Subject], split: dict[int, int], topic: int, n: int = 3) -> str:
    """A topic's distinctive words, from its subjects' labels and what they hold: frequent in it,
    rare outside."""
    inside: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    for i, t in split.items():
        words = set(_tokens(subs[i].label + " " + subs[i].holds))
        (inside if t == topic else outside).update(words)
    size = sum(1 for t in split.values() if t == topic)
    rest = max(1, len(split) - size)
    score = {w: c / size - outside[w] / rest for w, c in inside.items() if c > 1 or size == 1}
    return ", ".join(w for w, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:n]) or "(no distinctive words)"


def _view(subs: list[Subject], split: dict[int, int], vid: str, kind: str, title: str,
          labels: dict[int, str], holds: dict[int, str] | None = None, unsorted: list[int] | None = None) -> dict[str, Any]:
    members: dict[int, list[int]] = defaultdict(list)
    for i, t in sorted(split.items()):
        members[t].append(i)
    topics = [{"label": labels[t], **({"holds": holds[t]} if holds else {}), "subjects": [subs[i].id for i in ids]}
              for t, ids in sorted(members.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return {"id": vid, "kind": kind, "title": title, "topics": topics, "unsorted": [subs[i].id for i in unsorted or []]}


def words_view(subs: list[Subject]) -> dict[str, Any]:
    split = split_words(subs)
    return _view(subs, split, "words", "words", "By shared words and elements",
                 {t: word_label(subs, split, t) for t in set(split.values())})


# -- the LLM -----------------------------------------------------------------------------------------
def listing(subs: list[Subject]) -> str:
    """The proposal's list: every subject, or `LISTED` spread over the collection."""
    step = max(1.0, len(subs) / LISTED)
    picked = [subs[int(n * step)] for n in range(min(len(subs), LISTED))]
    return "\n".join(f"- {s.label}, {s.model}: {s.holds[:HOLDS_CHARS]}".rstrip(": ") for s in picked)


def batches(subs: list[Subject]) -> list[list[int]]:
    """Subjects in batches of `BATCH`, a family's together where it fits."""
    by_family: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(subs):
        by_family[s.family].append(i)
    out: list[list[int]] = []
    cur: list[int] = []
    for ids in by_family.values():
        if cur and len(cur) + len(ids) > BATCH:
            out.append(cur)
            cur = []
        for x in range(0, len(ids), BATCH):
            part = ids[x:x + BATCH]
            if len(part) == BATCH:
                out.append(part)
            else:
                cur += part
    if cur:
        out.append(cur)
    return out


def requests(subs: list[Subject]) -> int:
    return 1 + len(batches(subs)) if len(subs) >= 2 else 0


def llm_view(llm: Any, subs: list[Subject], concurrency: int = 1, advance: Any = None) -> dict[str, Any] | None:
    """The LLM's topics, every subject placed or left unsorted; None when the proposal failed."""

    def ask(template: Any, values: dict[str, str]) -> Any:
        try:
            return llm.ask(template, values, project="topics", inputs=(signature(subs),))
        except ReplayMiss as e:
            log.debug("topics: %s", e)
            return None

    models = len({s.family for s in subs})
    got = ask(TOPICS_PROPOSE, {"MODELS": str(models), "K": str(target(len(subs))), "SUBJECTS": listing(subs)})
    if advance:
        advance(1)
    topics = [t for t in ((_json(got) or {}).get("topics") or []) if isinstance(t, dict) and t.get("label")]
    if len(topics) < 2:
        return None
    menu = "\n".join(f"{n}. {t['label']}: {t.get('holds', '')}" for n, t in enumerate(topics, 1))

    def assign(batch: list[int]) -> dict[int, Any]:
        text = "\n".join(f"{n}. {subs[i].describe()}" for n, i in enumerate(batch, 1))
        reply = _json(ask(TOPICS_ASSIGN, {"TOPICS": menu, "SUBJECTS": text})) or {}
        if advance:
            advance(1)
        return {i: reply.get(str(n)) for n, i in enumerate(batch, 1)}

    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        answers = list(pool.map(assign, batches(subs)))
    split: dict[int, int] = {}
    unsorted = []
    for got_ in answers:
        for i, v in sorted(got_.items()):
            try:
                t = int(v) - 1
            except (TypeError, ValueError):
                t = -1
            if 0 <= t < len(topics):
                split[i] = t
            else:
                unsorted.append(i)
    return _view(subs, split, "llm", "llm", "Topics across models",
                 {t: str(topics[t]["label"])[:80] for t in range(len(topics))},
                 {t: str(topics[t].get("holds", ""))[:300] for t in range(len(topics))}, unsorted)


# -- the root file -----------------------------------------------------------------------------------
MIN_FAMILIES = 2  # topics across models need models to be across


def entry(subs: list[Subject], view: dict[str, Any] | None, asked: bool) -> dict[str, Any]:
    """The tree's topics record: its views, the default first (as a family's subjects, ADR-0031):
    the LLM's, unless it failed or left more than `UNSORTED_LIMIT` unsorted; then words."""
    rec: dict[str, Any] = {"signature": signature(subs), "subjects": len(subs)}
    if len({s.family for s in subs}) < MIN_FAMILIES:
        rec.update(views=[], default=None, ways="too few models")
        return rec
    views = [view] if view else []
    unsorted = len(view["unsorted"]) / len(subs) if view else 1.0
    if unsorted > UNSORTED_LIMIT:
        views.insert(0, words_view(subs))
    else:
        views.append(words_view(subs))
    rec.update(views=views, default=views[0]["id"],
               ways=("found" if view and unsorted == 0 else "incomplete" if view else "failed" if asked else "not asked"))
    return rec


def update(fams: list[Family], records: list[dict[str, Any]], before: dict[str, Any] | None, llm: Any = None,
           concurrency: int = 1, progress: Any = None) -> dict[str, Any]:
    """The topics record for `subjects.json`, from the families and their records: the last one
    when its subjects are unchanged and it is complete (or there is no LLM to ask); else asked
    again, or words alone."""
    subs = subjects(fams, {r["tokens"][0]: r for r in records})
    sig = signature(subs)
    can_ask = llm is not None and getattr(getattr(llm, "cfg", None), "text_model", None)
    if before and before.get("signature") == sig and (before.get("ways") in ("found", "too few models") or not can_ask):
        return before
    if not can_ask or len({s.family for s in subs}) < MIN_FAMILIES:
        return entry(subs, None, asked=False)
    if progress is not None:
        with progress.phase("topics across models", requests(subs), "request") as ph:
            view = llm_view(llm, subs, concurrency, ph.advance)
    else:
        view = llm_view(llm, subs, concurrency)
    return entry(subs, view, asked=True)

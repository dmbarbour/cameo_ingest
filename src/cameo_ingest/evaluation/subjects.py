"""Splitting models into subjects, for discovery (plan SB): the data, the candidate splits, and the
measures that need no judge.

A **family** is a set of versions of one model (ADR-0020's groups), or one model alone. A family's
**items** are its diagrams, each diagram once, however many versions hold it (the same id): the
newest version's copy, with every version that holds it. A **split** assigns each item of a family
to a group; every candidate split gets about the same number of groups (`target`), so that the
judges compare ways of splitting, not sizes.

Candidates (SB-02): `R` random, `P` the package tree, `G` communities of diagrams by the elements
they share (each element discounted by how many diagrams show it) and the relationships between
them, `T` clusters of their words.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from .. import groups as version_groups
from ..state import State

SEED = 1
WORD = re.compile(r"[a-z][a-z0-9]+")
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the this to with
which what how each their they these those diagram model package shows show showing describes defines""".split())  # noqa: SIM905


@dataclass
class Item:
    """A diagram of a family, once."""

    key: str
    name: str
    kind: str
    package: str  # its package path, "A::B"
    shows: set[str] = field(default_factory=set)  # element keys
    context: set[str] = field(default_factory=set)  # where the shown elements sit: their owners' paths
    about: str = ""  # the about text, if the tree has one (ADR-0029)
    owner: str = ""  # the element that owns it, when that isn't a package ("Attributes" of which block?)
    versions: list[str] = field(default_factory=list)  # tokens of the versions that hold it

    @property
    def words(self) -> str:
        return " ".join([self.name, self.owner, self.package.replace("::", " "), self.about])

    @property
    def title(self) -> str:
        return (self.name or "(unnamed)") + (f", of {self.owner}" if self.owner else "")


@dataclass
class Family:
    name: str
    tokens: list[str]  # newest first
    items: dict[str, Item]
    names: dict[str, str]  # element key -> name
    related: list[tuple[str, str]]  # relationships between element keys
    copies: int = 0  # diagrams in all versions, before each was taken once

    @property
    def label(self) -> str:
        return self.name + (f" ({len(self.tokens)} versions)" if len(self.tokens) > 1 else "")


def _catalog(root: Path, token: str) -> list[dict[str, Any]]:
    sha = token.removeprefix("sha256:")
    path = root / "by-sha256" / sha / "index" / "catalog.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def families(root: Path) -> list[Family]:
    """The tree's families, from its catalogs and its version groups."""
    state = State(root)
    try:
        report = version_groups.find(state.catalog(), state.fingerprint_ids(), {})
        written = {r["content_sha256"]: r["name"] for r in state.written()}
    finally:
        state.close()
    grouped = {m.sha for g in report.groups for m in g.members}
    sets = [[m.sha for m in g.members if m.sha in written] for g in report.groups]
    sets += [[sha] for sha in sorted(written, key=lambda s: (written[s].lower(), s)) if sha not in grouped]
    out = []
    for shas in sets:
        if not shas:
            continue
        items: dict[str, Item] = {}
        names: dict[str, str] = {}
        related: list[tuple[str, str]] = []
        copies = 0
        for sha in shas:  # newest first: its copy of a diagram is the one kept
            token = f"sha256:{sha}"
            about: dict[str, str] = {}
            recs = _catalog(root, token)
            packages = {r["key"] for r in recs if r["type"] == "package"}
            for r in recs:
                if r["type"] == "summary" and r.get("of"):
                    about.setdefault(r["of"][0], r["text"])
            for r in recs:  # the diagrams first: the elements that name them may come before them
                if r["type"] == "diagram":
                    copies += 1
                    it = items.get(r["key"])
                    if it is None:
                        own = r.get("owner") or ["", ""]
                        it = items[r["key"]] = Item(r["key"], r.get("name") or "", r.get("kind") or "",
                                                    r.get("package") or "", about=about.get(r["key"], ""),
                                                    owner="" if own[0] in packages else own[1])
                    it.versions.append(token)
            for r in recs:
                t = r["type"]
                if t == "relationship":
                    if r.get("source") and r.get("target"):
                        related.append((r["source"][0], r["target"][0]))
                elif t in ("element", "requirement", "package"):
                    names.setdefault(r["key"], r.get("name") or "")
                    owner = (r.get("where") or "").rpartition("::")[0]
                    for d, _ in r.get("diagrams") or []:
                        if d in items and token == items[d].versions[0]:
                            items[d].shows.add(r["key"])
                            if owner:
                                items[d].context.add(owner)
        out.append(Family(written[shas[0]], [f"sha256:{s}" for s in shas], items, names, related, copies))
    return out


def target(n: int) -> int:
    """How many groups a family of n items is split into: about the square root of n/2, 2 to 15."""
    return max(2, min(15, round(math.sqrt(n / 2))))


Split = dict[str, int]  # item key -> group


def split_random(f: Family, k: int) -> Split:
    rng = random.Random(SEED)
    keys = sorted(f.items)
    rng.shuffle(keys)
    return {key: i % k for i, key in enumerate(keys)}


def split_packages(f: Family, k: int) -> Split:
    """The package tree, cut at the depth whose number of groups is nearest k."""
    best: tuple[int, Split] | None = None
    deepest = max((len(it.package.split("::")) for it in f.items.values()), default=1)
    for depth in range(1, deepest + 1):
        paths = {key: "::".join(it.package.split("::")[:depth]) for key, it in f.items.items()}
        ids = {p: i for i, p in enumerate(sorted(set(paths.values())))}
        s = {key: ids[p] for key, p in paths.items()}
        if best is None or abs(len(ids) - k) < abs(max(best[1].values()) + 1 - k):
            best = (depth, s)
    return best[1] if best else {}


CONTEXT_WEIGHT = 0.5  # sharing where shown elements sit counts half as much as sharing an element


def _graph(f: Family) -> nx.Graph:
    """Diagrams joined by the elements they share, each discounted by how many diagrams show it
    (as search discounts common words); at half weight, by the owners of what they show (two
    activity diagrams of one block); and by relationships between what they show."""
    n = len(f.items)
    shown_by: dict[str, list[str]] = defaultdict(list)
    for key, it in f.items.items():
        for e in it.shows:
            shown_by[e].append(key)
    idf = {e: math.log(n / len(ds)) for e, ds in shown_by.items()}
    g = nx.Graph()
    g.add_nodes_from(sorted(f.items))
    w: Counter[tuple[str, str]] = Counter()
    within: dict[str, list[str]] = defaultdict(list)
    for key, it in f.items.items():
        for c in it.context:
            within[c].append(key)
    for features, scale in ((shown_by, 1.0), (within, CONTEXT_WEIGHT)):
        for e, ds in features.items():
            weight = scale * math.log(n / len(ds))
            if len(ds) < 2 or weight <= 0:
                continue
            ds = sorted(ds)
            for i, a in enumerate(ds):
                for b in ds[i + 1:]:
                    w[a, b] += weight
    for s, t in f.related:  # half weight: related, not the same
        for a in shown_by.get(s, []):
            for b in shown_by.get(t, []):
                if a != b:
                    w[min(a, b), max(a, b)] += 0.5 * min(idf.get(s, 0), idf.get(t, 0))
    g.add_weighted_edges_from((a, b, x) for (a, b), x in sorted(w.items()) if x > 0)
    return g


def split_graph(f: Family, k: int) -> Split:
    """Louvain communities (seeded) of `_graph`, then merged down to k: the smallest group joins
    the group it is most joined to, or, joined to none, the one whose package path it shares
    most of (a diagram that shows nothing, such as a table, goes by its package)."""
    g = _graph(f)
    comms = [set(c) for c in nx.community.louvain_communities(g, weight="weight", seed=SEED)]
    group = {key: i for i, c in enumerate(comms) for key in c}
    members = dict(enumerate(comms))

    def common(a: str, b: str) -> int:
        n = 0
        for x, y in zip(a.split("::"), b.split("::"), strict=False):
            if x != y:
                break
            n += 1
        return n

    def package(c: set[str]) -> str:
        return Counter(f.items[key].package for key in c).most_common(1)[0][0]

    least = 3 if len(f.items) >= 30 else 1  # groups under this are merged, even below k

    while len(members) > k or min(len(c) for c in members.values()) < least and len(members) > 1:
        small = min(members, key=lambda i: (len(members[i]), min(members[i])))
        ties: Counter[int] = Counter()
        for key in members[small]:
            for nb, data in g[key].items():
                if group[nb] != small:
                    ties[group[nb]] += data["weight"]
        if ties:
            into = max(ties, key=lambda i: (ties[i], -i))
        else:
            pkg = package(members[small])
            into = max((i for i in members if i != small),
                       key=lambda i: (common(pkg, package(members[i])), len(members[i]), -i))
        for key in members.pop(small):
            group[key] = into
            members[into].add(key)
    order = {i: n for n, i in enumerate(sorted(members, key=lambda i: (-len(members[i]), min(members[i]))))}
    return {key: order[i] for key, i in group.items()}


def _tokens(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def split_words(f: Family, k: int) -> Split:
    """Spherical k-means (seeded, k-means++ start) over TF-IDF of each diagram's name, package
    path, about text and the names it shows."""
    import numpy as np

    keys = sorted(f.items)
    docs = [_tokens(f.items[key].words + " " + " ".join(f.names.get(e, "") for e in sorted(f.items[key].shows)))
            for key in keys]
    vocab = {w: i for i, w in enumerate(sorted({w for d in docs for w in d}))}
    df = Counter(w for d in docs for w in set(d))
    x = np.zeros((len(docs), len(vocab)))
    for i, d in enumerate(docs):
        for w, c in Counter(d).items():
            x[i, vocab[w]] = (1 + math.log(c)) * math.log(len(docs) / df[w])
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    x = x / np.where(norms == 0, 1, norms)
    rng = np.random.default_rng(SEED)
    k = min(k, len(keys))
    centers = [x[rng.integers(len(keys))]]
    for _ in range(1, k):
        d = 1 - np.max(x @ np.array(centers).T, axis=1)
        p = np.clip(d, 0, None)
        centers.append(x[rng.choice(len(keys), p=p / p.sum())] if p.sum() > 0 else x[rng.integers(len(keys))])
    c = np.array(centers)
    labels = np.zeros(len(keys), dtype=int)
    for _ in range(50):
        new = np.argmax(x @ c.T, axis=1)
        if (new == labels).all() and _:
            break
        labels = new
        for j in range(k):
            m = x[labels == j]
            if len(m):
                v = m.sum(axis=0)
                c[j] = v / (np.linalg.norm(v) or 1)
    used = {j: i for i, j in enumerate(sorted(set(labels.tolist())))}
    return {key: used[int(j)] for key, j in zip(keys, labels, strict=True)}


SPLITS = {"R": split_random, "P": split_packages, "G": split_graph, "T": split_words}


def label(f: Family, s: Split, group: int, n: int = 3) -> str:
    """A group's distinctive words: frequent in it, rare outside (for E2 and E3 of plan SB, and the
    first look); P's groups are their package paths."""
    inside, outside, everywhere = Counter(), Counter(), Counter()
    for key, g in s.items():
        words = set(_tokens(f.items[key].title + " " + f.items[key].about))
        (inside if g == group else outside).update(words)
        everywhere.update(set(_tokens(f.items[key].about)))
    common = {w for w, c in everywhere.items() if c > 0.3 * len(s)}  # the about texts' own idiom
    size = sum(1 for g in s.values() if g == group)
    rest = max(1, len(s) - size)
    score = {w: c / size - outside[w] / rest for w, c in inside.items() if (c > 1 or size == 1) and w not in common}
    return ", ".join(w for w, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:n]) or "(no words)"


def measures(s: Split) -> dict[str, Any]:
    """Without judges: the number of groups, their balance and the largest group's share."""
    sizes = sorted(Counter(s.values()).values(), reverse=True)
    n = sum(sizes)
    entropy = -sum(x / n * math.log(x / n) for x in sizes)
    return {"groups": len(sizes), "largest": round(sizes[0] / n, 3) if n else 0.0,
            "balance": round(entropy / math.log(len(sizes)), 3) if len(sizes) > 1 else 0.0,
            "singletons": sum(1 for x in sizes if x == 1)}

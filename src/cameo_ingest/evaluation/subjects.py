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

import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from .. import subjects as production
from ..discovery import target, tokens  # noqa: F401 (target: the study's name)
from ..state import State
from ..subjects import Family, Item, Split, split_packages  # noqa: F401 (the study's names)
from ..subjects import split_shared as split_graph
from ..subjects import word_label as label  # noqa: F401 (the study's name)

SEED = 1


def families(root: Path) -> list[Family]:
    """The tree's families (`subjects.families`)."""
    state = State(root)
    try:
        return production.families(state, root)
    finally:
        state.close()


def split_random(f: Family, k: int) -> Split:
    rng = random.Random(SEED)
    keys = sorted(f.items)
    rng.shuffle(keys)
    return {key: i % k for i, key in enumerate(keys)}


def split_words(f: Family, k: int) -> Split:
    """Spherical k-means (seeded, k-means++ start) over TF-IDF of each diagram's name, package
    path, about text and the names it shows."""
    import numpy as np

    keys = sorted(f.items)
    docs = [tokens(f.items[key].words + " " + " ".join(f.names.get(e, "") for e in sorted(f.items[key].shows)))
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


def measures(s: Split) -> dict[str, Any]:
    """Without judges: the number of groups, their balance and the largest group's share."""
    sizes = sorted(Counter(s.values()).values(), reverse=True)
    n = sum(sizes)
    entropy = -sum(x / n * math.log(x / n) for x in sizes)
    return {"groups": len(sizes), "largest": round(sizes[0] / n, 3) if n else 0.0,
            "balance": round(entropy / math.log(len(sizes)), 3) if len(sizes) > 1 else 0.0,
            "singletons": sum(1 for x in sizes if x == 1)}

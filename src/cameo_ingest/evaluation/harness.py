"""Retrieval over an output tree, as the production stack is thought to work, and its measures
(plan RE-05).

- **Units:** the texts that are cut into windows: the chunks of `chunks.jsonl`, each keeping its
  chunk's metadata, so that a window's relevance can be decided from the element it is about.
- **Windows:** 512 tokens with 64 of overlap by default (`windows.py`), on the model's tokens.
- **Search:** dense (cosine over normalized vectors), BM25, and their fusion by reciprocal rank.
- **Measures:** per question, from graded relevance (2: answers it, 1: helps), with bootstrap
  confidence intervals over questions.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .windows import windows


@dataclass(frozen=True)
class Unit:
    id: str  # chunk id, or chunk id + "#w<n>" for a window
    text: str
    element_id: str | None
    kind: str
    project: str | None  # content token


def chunk_units(tree: Path) -> list[Unit]:
    out = []
    for line in (tree / "chunks.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        m = c["metadata"]
        out.append(Unit(c["id"], c["text"], m.get("element_id"), m["kind"], m.get("content")))
    return out


def windowed(units: list[Unit], model_name: str, size: int = 512, overlap: int = 64) -> list[Unit]:
    """Each unit cut into windows; a unit that fits keeps its id."""
    out = []
    for u in units:
        parts = windows(u.text, model_name, size, overlap)
        if len(parts) == 1:
            out.append(u)
        else:
            out += [Unit(f"{u.id}#w{i}", t, u.element_id, u.kind, u.project) for i, t in enumerate(parts)]
    return out


# -- search ---------------------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class BM25:
    """Okapi BM25 over the units' words (k1 = 1.2, b = 0.75)."""

    def __init__(self, texts: list[str], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        ids: dict[str, list[int]] = defaultdict(list)
        tfs: dict[str, list[int]] = defaultdict(list)
        self.lengths = np.zeros(len(texts), dtype=np.float32)
        for i, t in enumerate(texts):
            counts = Counter(words(t))
            self.lengths[i] = sum(counts.values())
            for w, n in counts.items():
                ids[w].append(i)
                tfs[w].append(n)
        # Compact arrays: tens of thousands of windows make millions of postings.
        self.postings = {w: (np.asarray(ids[w], dtype=np.int32), np.asarray(tfs[w], dtype=np.float32)) for w in ids}
        self.avg = float(self.lengths.mean()) if len(texts) else 1.0
        self.n = len(texts)

    def scores(self, query: str) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for w in set(words(query)):
            if w not in self.postings:
                continue
            ids, tf = self.postings[w]
            idf = math.log(1 + (self.n - len(ids) + 0.5) / (len(ids) + 0.5))
            norm = self.k1 * (1 - self.b + self.b * self.lengths[ids] / self.avg)
            s[ids] += idf * tf * (self.k1 + 1) / (tf + norm)
        return s


def top(scores: np.ndarray, k: int) -> list[int]:
    """Indices of the k highest scores, best first (ties by index, so runs are repeatable)."""
    k = min(k, len(scores))
    idx = np.argpartition(-scores, k - 1)[:k]
    return sorted(idx.tolist(), key=lambda i: (-scores[i], i))


def fuse(rankings: list[list[int]], k: int = 60, depth: int = 100, weights: list[float] | None = None) -> list[int]:
    """Reciprocal rank fusion of several rankings, each weighted (by default equally)."""
    score: dict[int, float] = defaultdict(float)
    for ranking, w in zip(rankings, weights or [1.0] * len(rankings), strict=True):
        for r, i in enumerate(ranking[:depth]):
            score[i] += w / (k + r + 1)
    return sorted(score, key=lambda i: (-score[i], i))


# -- measures -------------------------------------------------------------------------------------
def group_measures(ranking: list[int], covers: dict[int, frozenset[int]], groups: int) -> dict[str, float]:
    """For a question whose answer has several parts (`groups`; one per model, say): the share of
    the parts that the top 10 hold between them, and whether one unit of the top 10 holds them
    all. `covers`: unit -> the parts it holds."""
    seen: set[int] = set()
    complete = 0.0
    for i in ranking[:10]:
        got = covers.get(i, frozenset())
        seen |= got
        complete = max(complete, float(len(got) == groups))
    return {"coverage@10": len(seen) / groups if groups else 0.0, "complete@10": complete}



def measures(ranking: list[int], grades: dict[int, int]) -> dict[str, float]:
    """For one question: whether an answering unit (grade 2) is in the top 1, 5, 10 and 20; the
    reciprocal rank of the first within 10; and nDCG at 10 over all grades."""
    first = next((r for r, i in enumerate(ranking) if grades.get(i, 0) == 2), None)
    gains = [grades.get(i, 0) for i in ranking[:10]]
    dcg = sum((2 ** g - 1) / math.log2(r + 2) for r, g in enumerate(gains))
    ideal = sorted(grades.values(), reverse=True)[:10]
    idcg = sum((2 ** g - 1) / math.log2(r + 2) for r, g in enumerate(ideal))
    out = {f"hit@{k}": float(first is not None and first < k) for k in (1, 5, 10, 20)}
    out["mrr@10"] = 1 / (first + 1) if first is not None and first < 10 else 0.0
    out["ndcg@10"] = dcg / idcg if idcg else 0.0
    return out


def mean_ci(values: list[float], rounds: int = 2000, seed: int = 1) -> tuple[float, float, float]:
    """The mean, and a 95% bootstrap interval over the questions."""
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(rounds))
    return sum(values) / n, means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1]

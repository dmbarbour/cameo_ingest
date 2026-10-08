"""Lineage of models (plan LN-04): how two models that share element ids came to share them, told
by who made each side's own ids, and when (`fingerprint.marks`), with the evidence shown.

A pair is analysed when it shares ADR-0020's "related" share or more (20% of the smaller, 20
ids): real versions after much rework share less than its version rule asks (SAF's sample model
from 2021 to 2024, Jaccard 0.31). With the older first, it is:

- **copy:** neither has more than a few ids of its own (`COPY`): saved again, or copied;
- **branches:** each side has much of its own (`OWN`), mostly made after the shared part
  (`AFTER`), by makers the other side shares (`BRANCH`): one team's two branches;
- **root:** the same, by makers the other side lacks: rivals on a shared root (two bids);
- **version:** the newer's own ids were made after the shared part, and the older's own (those
  the newer dropped) mostly before it, with some of the newer's made by the older's makers
  (`SAME`): teams change, so the share is often under half (SAF 31% to 50%, TMT 21%);
- **derived:** the same, with almost none by the older's makers: built on the older by someone
  else (a bid on a customer's model);
- **related:** much of each side's own predates the shared part: a part, such as a library,
  taken into models made before it;
- **unknown:** too few of the own ids carry makers (`PARSED`) to tell: ADR-0020's rule decides
  (`groups.find`).

The thresholds are first guesses, measured on synthetic and public cases
(`docs/research/lineage-2026-10-07.md`). What a hex id identifies is inferred from Cameo's id
shape, not documented.
"""

from __future__ import annotations

import datetime as dt
import itertools
import os
from array import array
from dataclasses import dataclass, field
from typing import Any

from . import groups
from .fingerprint import NO_MAKER, unpack_list, unpack_marks
from .groups import RELATED_COVER, RELATED_MIN, utc

COPY = 0.001  # own ids, as a share of a side (or COPY_MIN ids): under this, a side adds nothing
COPY_MIN = 2
OWN = 0.03  # own ids, as a share of a side, at least OWN_MIN of them: a side's own work
OWN_MIN = 20
AFTER = 0.6  # of a side's own ids with a day: made after the shared part's latest
SAME = 0.15  # of the newer's own ids with a maker: made by the older's makers, for a version
BRANCH = 0.6  # of each side's own ids with a maker: made by the other's makers, for branches
KEPT = 0.5  # Jaccard, at least, for a newer with nothing of its own to be a version that dropped the rest
PARSED = 0.3  # of a side's own ids: carrying a maker, for the makers to tell
LATEST = 0.95  # the shared part's latest day: this quantile of its days (a few late ids aside)


@dataclass
class Model:
    sha: str
    name: str
    saved: str | None  # ISO
    paths: list[str]
    hashes: array  # sorted
    makers: list[str]
    who: array
    when: array


@dataclass
class Side:
    sha: str
    name: str
    ids: int
    own: int
    parsed: float  # of its own ids, the share with a maker
    same: float  # of its own ids with a maker, the share made by makers the other side has
    after: float  # of its own ids with a day, the share made after the shared part's latest
    first: str | None  # its own ids' first and last days of making
    last: str | None
    saved: str | None
    makers: list[str] = field(default_factory=list)  # its own ids' makers, most first


@dataclass
class Pair:
    a: Side  # the older (by save time)
    b: Side
    shared: int
    cover: float  # of the smaller
    jaccard: float
    shared_latest: str | None  # the shared part's latest day of making
    folder: str  # the paths' common folder, or ""
    kind: str
    why: str


def _day(d: int | None) -> str | None:
    return (dt.date(1970, 1, 1) + dt.timedelta(days=d)).isoformat() if d else None


def _side(m: Model, own_idx: list[int], other_makers: set[str], latest: int | None) -> Side:
    made = [m.makers[m.who[i]] for i in own_idx if m.who[i] != NO_MAKER]
    days = sorted(m.when[i] for i in own_idx if m.when[i])
    counts: dict[str, int] = {}
    for x in made:
        counts[x] = counts.get(x, 0) + 1
    return Side(
        m.sha, m.name, len(m.hashes), len(own_idx),
        parsed=round(len(made) / len(own_idx), 3) if own_idx else 1.0,
        same=round(sum(1 for x in made if x in other_makers) / len(made), 3) if made else 0.0,
        after=round(sum(1 for d in days if latest is not None and d > latest) / len(days), 3) if days else 0.0,
        first=_day(days[0]) if days else None, last=_day(days[-1]) if days else None, saved=m.saved,
        makers=sorted(counts, key=lambda x: (-counts[x], x))[:5])


def _folder(a: list[str], b: list[str]) -> str:
    best = ""
    for x, y in itertools.product(a, b):
        common = os.path.commonpath([os.path.dirname(x), os.path.dirname(y)]) if x and y else ""
        if len(common) > len(best):
            best = common
    return best


def compare(x: Model, y: Model) -> Pair | None:
    """The pair's lineage, or None when it shares too little to be related."""
    ix = {h: i for i, h in enumerate(x.hashes)}
    shared_x = [ix[h] for h in y.hashes if h in ix]
    shared = len(shared_x)
    smaller = min(len(x.hashes), len(y.hashes))
    if not shared or not smaller:
        return None
    cover, jaccard = shared / smaller, shared / (len(x.hashes) + len(y.hashes) - shared)
    if not (cover >= RELATED_COVER and shared >= RELATED_MIN):
        return None
    a, b = (x, y) if (utc(x.saved) if x.saved else "", x.sha) <= (utc(y.saved) if y.saved else "", y.sha) else (y, x)
    ia = {h: i for i, h in enumerate(a.hashes)}
    ib = {h: i for i, h in enumerate(b.hashes)}
    in_both = [h for h in a.hashes if h in ib]
    days = sorted(a.when[ia[h]] for h in in_both if a.when[ia[h]])
    latest = days[min(len(days) - 1, int(LATEST * len(days)))] if days else None
    a_own = [i for i, h in enumerate(a.hashes) if h not in ib]
    b_own = [i for i, h in enumerate(b.hashes) if h not in ia]

    def makers_of(m: Model, idx: list[int] | range) -> set[str]:
        return {m.makers[m.who[i]] for i in idx if m.who[i] != NO_MAKER}

    a_all, b_all = makers_of(a, range(len(a.hashes))), makers_of(b, range(len(b.hashes)))
    sa = _side(a, a_own, b_all, latest)
    sb = _side(b, b_own, a_all, latest)
    folder = _folder(a.paths, b.paths)
    pair = Pair(sa, sb, shared, round(cover, 3), round(jaccard, 3), _day(latest), folder, "", "")
    pair.kind, pair.why = classify(pair)
    return pair


def classify(p: Pair) -> tuple[str, str]:
    """The pair's kind, and why, in a sentence (`Pair.a` the older)."""
    a, b = p.a, p.b

    def few(s: Side) -> bool:
        return s.own <= max(COPY_MIN, COPY * s.ids)

    def substantial(s: Side) -> bool:
        return s.own >= OWN_MIN and s.own >= OWN * s.ids

    if few(a) and few(b):
        return "copy", f"each has {a.own:,} and {b.own:,} ids of its own: the same model, saved again"
    if few(b) and p.jaccard >= KEPT:
        return "version", f"the newer has only {b.own:,} ids of its own, and dropped {a.own:,} of the older's: a later version"
    if b.parsed < PARSED:
        return "unknown", f"too few of the newer's {b.own:,} ids of its own name their makers ({b.parsed:.0%}) to tell"
    if substantial(a) and substantial(b) and a.after >= AFTER and b.after >= AFTER:
        if a.parsed < PARSED:
            return "unknown", f"too few of the older's {a.own:,} ids of its own name their makers ({a.parsed:.0%}) to tell"
        if a.same >= BRANCH and b.same >= BRANCH:
            return "branches", (f"each has much of its own ({a.own:,} and {b.own:,} ids), made after the shared part, "
                                "by makers both share: one team's branches")
        return "root", (f"each has much of its own ({a.own:,} and {b.own:,} ids), made after the shared part "
                        f"(to {p.shared_latest}), by makers the other lacks ({', '.join(a.makers[:2])}; "
                        f"{', '.join(b.makers[:2])}): rivals on a shared root")
    if b.after >= AFTER and a.after < AFTER:
        if b.same >= SAME:
            return "version", (f"the newer's {b.own:,} ids of its own were made after the shared part, "
                               f"{b.first} to {b.last}, {b.same:.0%} by the older's makers: a later version")
        return "derived", (f"the newer's {b.own:,} ids of its own were made after the shared part by others "
                           f"({', '.join(b.makers[:2])}), {b.first} to {b.last}: built on the older by someone else")
    return "related", (f"they share {p.shared:,} ids, {p.cover:.0%} of the smaller, and much of each one's own "
                       "predates them: a part, such as a library")


def models(state: Any, include_removed: bool = False) -> list[Model]:
    """The tree's fingerprinted models, with their ids' makers and days; a model fingerprinted
    before plan LN has none (its pairs are `unknown`, and ADR-0020's rule decides)."""
    ids = state.fingerprint_ids()
    marks = state.id_marks()
    out = []
    for r in state.catalog():
        sha = r["sha256"]
        if (r["status"] == "removed" and not include_removed) or sha not in ids:
            continue
        hashes = unpack_list(ids[sha])
        if sha in marks:
            makers, who, when = marks[sha]
            w, d = unpack_marks(who, when)
        else:
            makers, w, d = [], array("H", [NO_MAKER] * len(hashes)), array("I", [0] * len(hashes))
        out.append(Model(sha, r["name"], r["saved"], [s["path"] for s in state.sightings(sha)], hashes, makers, w, d))
    return out


def pairs(state: Any, include_removed: bool = False) -> list[Pair]:
    """Every related pair of the tree's models, with its lineage."""
    ms = sorted(models(state, include_removed), key=lambda m: (m.name.lower(), m.sha))
    sets = {m.sha: set(m.hashes) for m in ms}
    out = []
    for x, y in itertools.combinations(ms, 2):
        if sets[x.sha].isdisjoint(sets[y.sha]):
            continue
        p = compare(x, y)
        if p is not None:
            out.append(p)
    return out


# The kin of a model, as it stands to the other: (kind, the older's side) -> what the model is to the other.
_AS_OLDER = {"derived": "built-on", "root": "root", "branches": "branches"}
_AS_NEWER = {"derived": "derived", "root": "root", "branches": "branches"}


def facts(state: Any) -> dict[str, dict[str, Any]]:
    """What the exports show of each model (plan LN-06), by token: its save time and Cameo version,
    its family (the newest version's token), its rank there (0, the newest), how many versions, its
    kin (`[token, how it stands]`: `derived` from the other, `built-on` by the other, `root` shared,
    `branches`) and the models related to it."""
    rows = {r["sha256"]: r for r in state.catalog() if r["status"] != "removed"}
    report = groups.find(state.catalog(), state.fingerprint_ids(), {}, pairs=pairs(state))
    out: dict[str, dict[str, Any]] = {}
    for sha, r in rows.items():
        out[f"sha256:{sha}"] = {"saved": r["saved"], "exporter": r["exporter"], "family": f"sha256:{sha}", "rank": 0,
                                "versions": 1, "kin": [], "related": []}
    for g in report.groups:
        for rank, m in enumerate(g.members):
            if f"sha256:{m.sha}" in out:
                out[f"sha256:{m.sha}"].update(family=f"sha256:{g.members[0].sha}", rank=rank, versions=len(g.members))
    for a, b, kind, _ in report.kin:
        ta, tb = f"sha256:{a.sha}", f"sha256:{b.sha}"
        if ta in out and tb in out:
            out[ta]["kin"].append([tb, _AS_OLDER[kind]])
            out[tb]["kin"].append([ta, _AS_NEWER[kind]])
    for a, b, _, _ in report.related:
        ta, tb = f"sha256:{a.sha}", f"sha256:{b.sha}"
        if ta in out and tb in out:
            out[ta]["related"].append(tb)
            out[tb]["related"].append(ta)
    return out

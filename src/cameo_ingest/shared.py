"""The same item in several models, and how its copies differ (plan SH).

**Matches,** strongest first (D1), each shown with its basis:
- `element`: the same element id: versions, a model and the bids built on it, a used library;
- `requirement id`: the same requirement Id on different elements, each the only one with that
  Id in its model: a bidder copying the customer's requirements, a DOORS import;
- `name`: the same type, kind and name, each the only one so named in its model, between models
  that lineage relates (versions, kin, related): a name alone is too weak elsewhere.

**Differences** between two copies are what people deliberately edit (D2), as far as the catalog
holds it: the name, the requirement Id, the text (requirement text and documentation), the
stereotypes and their tagged values, the relationships (lined up by the other end's id, else by its
label), what it owns (its listed members), what a diagram shows, and its package. Tool records
(stamps, authors, layout) aren't in the catalog's comparison.

`find` reads the catalogs twice: once to count which keys, Ids and names recur, once to keep the
copies that do.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

ITEMS = ("requirement", "element", "diagram", "package")
BASES = ("element", "requirement id", "name")  # strongest first


@dataclass
class Copy:
    token: str
    key: str
    type: str
    kind: str
    name: str
    rid: str | None
    text: str  # a digest
    stereotypes: tuple[str, ...]
    tagged: tuple[tuple[str, str], ...]
    relations: tuple[tuple[str, str, str, str, str], ...]  # (kind, direction, other's key, other's label, phrase)
    owns: tuple[str, ...]  # its members' names
    shows: tuple[tuple[str, str], ...]  # a diagram's shapes: (key, name)
    place: str


@dataclass
class Link:
    other: Copy
    basis: str
    differences: list[str] = field(default_factory=list)  # empty: the same


def _digest(text: str | None) -> str:
    return hashlib.sha256(" ".join((text or "").split()).encode()).hexdigest()[:16]


def _copies(token: str, records: list[dict[str, Any]]) -> dict[str, Copy]:
    owns: dict[str, list[str]] = defaultdict(list)
    shows: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in records:
        if r.get("listed_in"):
            owns[r["listed_in"][0]].append(r["name"])
        if r["type"] in ITEMS:
            for d, _ in r.get("diagrams") or []:
                shows[d].append((r["key"], r["name"]))
    out = {}
    for r in records:
        if r["type"] not in ITEMS:
            continue
        out[r["key"]] = Copy(
            token, r["key"], r["type"], r.get("kind") or "", r.get("name") or "", r.get("id"), _digest(r.get("text")),
            tuple(sorted(r.get("stereotypes") or [])), tuple(sorted((r.get("tagged") or {}).items())),
            tuple(sorted((rel[1], rel[2], rel[4], rel[5], rel[3]) for rel in r.get("relations") or [])),
            tuple(sorted(owns.get(r["key"], []))), tuple(sorted(shows.get(r["key"], []))), r.get("package") or "")
    return out


def _added_removed(here: Iterable[str], there: Iterable[str]) -> tuple[list[str], list[str]]:
    a, b = Counter(here), Counter(there)
    return sorted((a - b).elements()), sorted((b - a).elements())


def differences(a: Copy, b: Copy) -> list[str]:
    """What `a` has that `b` differs in, as short phrases ("text", "name: X here, Y there", ...)."""
    out = []
    if a.name != b.name:
        out.append(f"name: {a.name} here, {b.name} there")
    if a.rid != b.rid:
        out.append(f"requirement Id: {a.rid or 'none'} here, {b.rid or 'none'} there")
    if a.text != b.text:
        out.append("text")
    plus, minus = _added_removed(a.stereotypes, b.stereotypes)
    if plus or minus:
        out.append("stereotypes" + _pm(plus, minus))
    if a.tagged != b.tagged:
        da, db = dict(a.tagged), dict(b.tagged)
        changed = sorted(k for k in set(da) | set(db) if da.get(k) != db.get(k))
        out.append("tagged values: " + ", ".join(changed))
    # relationships: by the other end's id where the other copy's model has the same id, else by its label
    there_keys = {(k, d, o) for k, d, o, _, _ in b.relations}
    here_keys = {(k, d, o) for k, d, o, _, _ in a.relations}
    here = Counter((k, d, lab, ph) for k, d, o, lab, ph in a.relations if (k, d, o) not in there_keys)
    there = Counter((k, d, lab, ph) for k, d, o, lab, ph in b.relations if (k, d, o) not in here_keys)
    # unmatched by the other end's id, matched by its label: the same relationship to a re-made element
    plus, minus = _added_removed([f"{ph} {lab}" for k, d, lab, ph in (here - there).elements()],
                                 [f"{ph} {lab}" for k, d, lab, ph in (there - here).elements()])
    if plus or minus:
        out.append("relationships" + _pm(plus, minus))
    plus, minus = _added_removed(a.owns, b.owns)
    if plus or minus:
        out.append("members" + _pm(plus, minus))
    there_shown = {k for k, _ in b.shows}
    here_shown = {k for k, _ in a.shows}
    plus, minus = _added_removed([n for k, n in a.shows if k not in there_shown], [n for k, n in b.shows if k not in here_shown])
    if plus or minus:
        out.append("shows" + _pm(plus, minus))
    if a.place != b.place:
        here, there = _parted(a.place, b.place)
        out.append(f"package: {here} here, {there} there")
    return out


def _parted(a: str, b: str) -> tuple[str, str]:
    """Two package paths from where they part ("…::IRIS::Imager", "…::IFS::Imager")."""
    pa, pb = a.split("::") if a else [], b.split("::") if b else []
    n = 0
    while n < min(len(pa), len(pb)) and pa[n] == pb[n]:
        n += 1
    start = max(0, n - 1)  # the last part they share, for context

    def show(parts: list[str]) -> str:
        return ("…::" if start else "") + "::".join(parts[start:]) if parts else "(the root)"
    return show(pa), show(pb)


def _pm(plus: list[str], minus: list[str], most: int = 3) -> str:
    def few(xs: list[str]) -> str:
        return ", ".join(xs[:most]) + (f" and {len(xs) - most} more" if len(xs) > most else "")
    parts = ([f"only here: {few(plus)}"] if plus else []) + ([f"only there: {few(minus)}"] if minus else [])
    return " (" + "; ".join(parts) + ")"


def find(catalogs: Callable[[], Iterable[Any]], related: Callable[[str, str], bool]) -> dict[tuple[str, str], list[Link]]:
    """Each copy's matches in other models, by (token, key): `catalogs` gives the projects'
    catalogs (`catalog.ProjectCatalog`) afresh at each call; `related` says whether two models'
    tokens are related by lineage."""
    keys: dict[str, set[str]] = defaultdict(set)
    rids: dict[str, Counter[str]] = defaultdict(Counter)  # rid -> token -> how many elements
    names: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for p in catalogs():
        token = p.header.get("token") or ""
        for r in p.records:
            if r["type"] not in ITEMS:
                continue
            keys[r["key"]].add(token)
            if r["type"] == "requirement" and r.get("id"):
                rids[r["id"]][token] += 1
            if r.get("name"):
                names[r["type"], r.get("kind") or "", r["name"]][token] += 1
    shared_keys = {k for k, ts in keys.items() if len(ts) > 1}
    shared_rids = {rid for rid, ts in rids.items() if len(ts) > 1}
    shared_names = {n for n, ts in names.items() if len(ts) > 1}
    del keys
    by_key: dict[str, list[Copy]] = defaultdict(list)
    by_rid: dict[str, list[Copy]] = defaultdict(list)
    by_name: dict[tuple[str, str, str], list[Copy]] = defaultdict(list)
    for p in catalogs():
        token = p.header.get("token") or ""
        for c in _copies(token, p.records).values():
            in_key = c.key in shared_keys
            in_rid = c.type == "requirement" and c.rid in shared_rids and rids[c.rid][token] == 1
            name = (c.type, c.kind, c.name)
            in_name = c.name and name in shared_names and names[name][token] == 1
            if in_key:
                by_key[c.key].append(c)
            if in_rid:
                by_rid[c.rid].append(c)
            if in_name:
                by_name[name].append(c)
    out: dict[tuple[str, str], list[Link]] = defaultdict(list)
    linked: set[tuple[str, str, str, str]] = set()

    def link(a: Copy, b: Copy, basis: str) -> None:
        if a.token == b.token or (a.token, a.key, b.token, b.key) in linked:
            return
        linked.add((a.token, a.key, b.token, b.key))
        linked.add((b.token, b.key, a.token, a.key))
        out[a.token, a.key].append(Link(b, basis, differences(a, b)))
        out[b.token, b.key].append(Link(a, basis, differences(b, a)))

    for basis, groups, need_related in zip(BASES, (by_key, by_rid, by_name), (False, False, True), strict=True):
        for copies in groups.values():
            for i, a in enumerate(copies):
                for b in copies[i + 1:]:
                    if need_related and not related(a.token, b.token):
                        continue
                    link(a, b, basis)
    return dict(out)


def related_by(facts: dict[str, dict[str, Any]]) -> Callable[[str, str], bool]:
    """Whether two models are related by lineage (`lineage.facts`): versions of one family, kin, or
    sharing a part."""
    pairs = set()
    for token, f in facts.items():
        for other, _ in f.get("kin", []):
            pairs.add(frozenset((token, other)))
        for other in f.get("related", []):
            pairs.add(frozenset((token, other)))

    def related(a: str, b: str) -> bool:
        fa, fb = facts.get(a, {}), facts.get(b, {})
        return (fa.get("family") is not None and fa.get("family") == fb.get("family")) or frozenset((a, b)) in pairs
    return related

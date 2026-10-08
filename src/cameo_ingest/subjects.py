"""Subjects for discovery (plan SB, ADR-0031): each family of versions of a model, its diagrams
split into subjects a person can browse, and group search results by.

- **A family** is a set of versions of one model (copies and versions by lineage, ADR-0032), or
  one model alone: rivals on a shared root stay apart, each with its own diagrams. Its
  **items** are its diagrams, each once, however many versions hold it (by id), the newest's copy.
- **Views** of a family, the default first:
  - **the LLM's ways:** the tree's text model proposes about `WAYS` ways to organize the diagrams,
    each on its own principle, with labelled subjects, then assigns each diagram to a subject of
    each way, in batches cut by package (a new diagram changes only its package's batch);
  - **shared elements,** the fallback: communities of diagrams by the elements they show and
    where those sit, labelled by their distinctive words. The default when the tree has no LLM,
    the proposal failed, or more than `UNSORTED_LIMIT` of a way's diagrams are unsorted;
  - **packages,** always: the package tree, cut where it gives about as many groups.
- **Never a guess:** diagrams a way couldn't assign stay under "Not sorted yet", and the next run
  asks for them again (failures aren't stored).

`update` writes `subjects.json` at the root. With a session, it asks for the ways of each family
whose ways are missing, changed or incomplete; without one (`remove`, `prune`), it keeps what the
last run found for an unchanged family, and gives a changed one the fallback until the next run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from . import groups as version_groups
from .llm import ReplayMiss
from .progress import QUIET, Progress
from .prompts import SUBJECTS_ASSIGN, SUBJECTS_PROPOSE
from .treefiles import index_file, project_dir, read_jsonl

log = logging.getLogger(__name__)

FILE = "subjects.json"
FORMAT = 1
SEED = 1
MIN_ITEMS = 8  # a smaller family isn't split: its packages are its one view
WAYS = 3
BATCH = 30  # diagrams an assignment request
EXAMPLES = 60  # example diagrams in an outline
ABOUT_CHARS = 200
UNSORTED_LIMIT = 0.05  # more unsorted than this, and the fallback is the default view
CONTEXT_WEIGHT = 0.5  # sharing where shown elements sit counts half as much as sharing an element
UNSORTED = "Not sorted yet"
UNSORTED_NOTE = "The LLM gave no answer for these; the next run asks again."

WORD = re.compile(r"[a-z][a-z0-9]+")
STOP = frozenset("""a an and are as at be by for from has have in into is it its of on or that the this to with
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
    about: str = ""  # its about text, if the tree has one (ADR-0029)
    owner: str = ""  # the element that owns it, when that isn't a package ("Attributes" of which block?)
    versions: list[str] = field(default_factory=list)  # tokens of the versions that hold it, newest first

    @property
    def title(self) -> str:
        return (self.name or "(unnamed)") + (f", of {self.owner}" if self.owner else "")

    @property
    def words(self) -> str:
        return " ".join([self.name, self.owner, self.package.replace("::", " "), self.about])

    def describe(self) -> str:
        about = self.about.replace("\n", " ")
        about = about[:ABOUT_CHARS] + ("…" if len(about) > ABOUT_CHARS else "")
        return f"{self.title} ({self.kind})" + (f": {about}" if about else "")


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

    @property
    def signature(self) -> str:
        """What the family's subjects depend on: its versions, and its diagrams' names and places."""
        h = hashlib.sha256()
        for t in self.tokens:
            h.update(t.encode())
        for key, it in sorted(self.items.items()):
            h.update(f"\0{key}\0{it.name}\0{it.package}\0{it.about}".encode())
        return h.hexdigest()[:16]


def _catalog(out: Path, token: str) -> list[dict[str, Any]]:
    return read_jsonl(index_file(project_dir(out, token), "catalog"), missing_ok=True)


def families(state: Any, out: Path) -> list[Family]:
    """The tree's families, from its version groups and its projects' catalogs."""
    from . import lineage

    report = version_groups.find(state.catalog(), state.fingerprint_ids(), {}, pairs=lineage.pairs(state))
    written = {r["content_sha256"]: r["name"] for r in state.written()}
    grouped = {m.sha for g in report.groups for m in g.members}
    sets = [[m.sha for m in g.members if m.sha in written] for g in report.groups]
    sets += [[sha] for sha in sorted(written, key=lambda s: (written[s].lower(), s)) if sha not in grouped]
    out_: list[Family] = []
    for shas in sets:
        if shas:
            out_.append(_family(out, written[shas[0]], [f"sha256:{s}" for s in shas]))
    return out_


def _family(out: Path, name: str, tokens: list[str]) -> Family:
    items: dict[str, Item] = {}
    names: dict[str, str] = {}
    related: list[tuple[str, str]] = []
    copies = 0
    for token in tokens:  # newest first: its copy of a diagram is the one kept
        recs = _catalog(out, token)
        packages = {r["key"] for r in recs if r.get("type") == "package"}
        about = {}
        for r in recs:
            if r.get("type") == "summary" and r.get("of"):
                about.setdefault(r["of"][0], r.get("text") or "")
        for r in recs:  # the diagrams first: the elements that name them may come before them
            if r.get("type") == "diagram":
                copies += 1
                it = items.get(r["key"])
                if it is None:
                    own = r.get("owner") or ["", ""]
                    it = items[r["key"]] = Item(r["key"], r.get("name") or "", r.get("kind") or "",
                                                r.get("package") or "", about=about.get(r["key"], ""),
                                                owner="" if own[0] in packages else own[1])
                it.versions.append(token)
        for r in recs:
            t = r.get("type")
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
    return Family(name, tokens, items, names, related, copies)


def target(n: int) -> int:
    """How many subjects a family of n diagrams is split into: about the square root of n/2, 2 to 15."""
    return max(2, min(15, round(math.sqrt(n / 2))))


Split = dict[str, int]  # item key -> group


# -- shared elements: the fallback -------------------------------------------------------------------
def _graph(f: Family) -> nx.Graph:
    """Diagrams joined by the elements they share, each discounted by how many diagrams show it
    (as search discounts common words); at half weight, by the owners of what they show; and by
    the relationships between what they show."""
    n = len(f.items)
    shown_by: dict[str, list[str]] = defaultdict(list)
    within: dict[str, list[str]] = defaultdict(list)
    for key, it in sorted(f.items.items()):  # in order throughout: sums and ties, whatever the hash seed
        for e in sorted(it.shows):
            shown_by[e].append(key)
        for c in sorted(it.context):
            within[c].append(key)
    g = nx.Graph()
    g.add_nodes_from(sorted(f.items))
    w: Counter[tuple[str, str]] = Counter()
    for features, scale in ((shown_by, 1.0), (within, CONTEXT_WEIGHT)):
        for e, ds in sorted(features.items()):
            weight = scale * math.log(n / len(ds))
            if len(ds) < 2 or weight <= 0:
                continue
            ds = sorted(ds)
            for i, a in enumerate(ds):
                for b in ds[i + 1:]:
                    w[a, b] += weight
    idf = {e: math.log(n / len(ds)) for e, ds in shown_by.items()}
    for s, t in f.related:  # half weight: related, not the same
        for a in shown_by.get(s, []):
            for b in shown_by.get(t, []):
                if a != b:
                    w[min(a, b), max(a, b)] += 0.5 * min(idf.get(s, 0), idf.get(t, 0))
    g.add_weighted_edges_from((a, b, x) for (a, b), x in sorted(w.items()) if x > 0)
    return g


def _common(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.split("::"), b.split("::"), strict=False):
        if x != y:
            break
        n += 1
    return n


def louvain(g: nx.Graph) -> list[set[str]]:
    """Louvain communities, the same whatever the hash seed: networkx gathers nodes in sets, whose
    order for strings depends on it, so the nodes go in as numbers, in sorted order."""
    names = sorted(g.nodes)
    num = nx.Graph()
    num.add_nodes_from(range(len(names)))
    index = {n: i for i, n in enumerate(names)}
    num.add_weighted_edges_from(sorted((min(index[a], index[b]), max(index[a], index[b]), d["weight"])
                                       for a, b, d in g.edges(data=True)))
    return [{names[i] for i in c} for c in nx.community.louvain_communities(num, weight="weight", seed=SEED)]


def split_shared(f: Family, k: int) -> Split:
    """Louvain communities (seeded) of `_graph`, then merged down to k, and groups under 3 merged
    in any case: the smallest group joins the group it is most joined to, or, joined to none, the
    one whose package path it shares most of (a table, which shows nothing, goes by its package)."""
    g = _graph(f)
    comms = louvain(g)
    group = {key: i for i, c in enumerate(comms) for key in c}
    members = dict(enumerate(comms))
    least = 3 if len(f.items) >= 30 else 1

    def package(c: set[str]) -> str:
        return Counter(f.items[key].package for key in sorted(c)).most_common(1)[0][0]

    while len(members) > 1 and (len(members) > k or min(len(c) for c in members.values()) < least):
        small = min(members, key=lambda i: (len(members[i]), min(members[i])))
        ties: Counter[int] = Counter()
        for key in sorted(members[small]):
            for nb, data in sorted(g[key].items()):
                if group[nb] != small:
                    ties[group[nb]] += data["weight"]
        if ties:
            into = max(ties, key=lambda i: (ties[i], -i))
        else:
            pkg = package(members[small])
            into = max((i for i in members if i != small),
                       key=lambda i: (_common(pkg, package(members[i])), len(members[i]), -i))
        for key in members.pop(small):
            group[key] = into
            members[into].add(key)
    order = {i: n for n, i in enumerate(sorted(members, key=lambda i: (-len(members[i]), min(members[i]))))}
    return {key: order[i] for key, i in group.items()}


def split_packages(f: Family, k: int) -> Split:
    """The package tree, cut at the depth whose number of groups is nearest k."""
    best: Split = {}
    deepest = max((len(it.package.split("::")) for it in f.items.values()), default=1)
    for depth in range(1, deepest + 1):
        paths = {key: "::".join(it.package.split("::")[:depth]) for key, it in f.items.items()}
        ids = {p: i for i, p in enumerate(sorted(set(paths.values())))}
        s = {key: ids[p] for key, p in paths.items()}
        if not best or abs(len(ids) - k) < abs(max(best.values()) + 1 - k):
            best = s
    return best


def _tokens(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def word_label(f: Family, s: Split, group: int, n: int = 3) -> str:
    """A group's distinctive words: frequent in it, rare outside, leaving out the about texts' own
    idiom (words in more than 30% of them)."""
    inside: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    everywhere: Counter[str] = Counter()
    for key, g in s.items():
        words = set(_tokens(f.items[key].title + " " + f.items[key].about))
        (inside if g == group else outside).update(words)
        everywhere.update(set(_tokens(f.items[key].about)))
    common = {w for w, c in everywhere.items() if c > 0.3 * len(s)}
    size = sum(1 for g in s.values() if g == group)
    rest = max(1, len(s) - size)
    score = {w: c / size - outside[w] / rest for w, c in inside.items() if (c > 1 or size == 1) and w not in common}
    return ", ".join(w for w, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:n]) or "(no distinctive words)"


def package_label(f: Family, s: Split, group: int) -> str:
    parts = [f.items[k].package.split("::") for k, x in s.items() if x == group]
    common = []
    for level in zip(*parts, strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    return "::".join(common[-2:]) or "(the model's root)"


def _view(f: Family, s: Split, vid: str, kind: str, title: str, labels: dict[int, str]) -> dict[str, Any]:
    groups: dict[int, list[str]] = defaultdict(list)
    for key, g in s.items():
        groups[g].append(key)
    subjects = [{"label": labels[g], "diagrams": sorted(ks)} for g, ks in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    return {"id": vid, "kind": kind, "title": title, "subjects": subjects}


def shared_view(f: Family) -> dict[str, Any]:
    s = split_shared(f, target(len(f.items)))
    return _view(f, s, "shared", "shared-elements", "By shared elements",
                 {g: word_label(f, s, g) for g in set(s.values())})


def package_view(f: Family) -> dict[str, Any]:
    s = split_packages(f, target(len(f.items)))
    return _view(f, s, "packages", "packages", "By package", {g: package_label(f, s, g) for g in set(s.values())})


# -- the LLM's ways ----------------------------------------------------------------------------------
def outline(f: Family) -> str:
    counts: Counter[str] = Counter()
    for it in f.items.values():
        parts = (it.package or "(the model's root)").split("::")
        for depth in range(1, min(len(parts), 3) + 1):
            counts["::".join(parts[:depth])] += 1
    lines = ["Packages (diagrams):"] + [f"- {p} ({n})" for p, n in sorted(counts.items())][:80]
    keys = sorted(f.items)
    step = max(1, len(keys) // EXAMPLES)
    lines += ["", "Example diagrams:"] + [f"- {f.items[k].describe()}" for k in keys[::step][:EXAMPLES]]
    return "\n".join(lines)


def batches(f: Family) -> list[list[str]]:
    """Diagrams in batches cut by package, so that a new diagram changes its package's batch only:
    a package's diagrams in order, a large one in several batches, small ones together up to BATCH."""
    by_pkg: dict[str, list[str]] = defaultdict(list)
    for key, it in sorted(f.items.items()):
        by_pkg[it.package].append(key)
    out: list[list[str]] = []
    cur: list[str] = []
    for _, keys in sorted(by_pkg.items()):
        for i in range(0, len(keys), BATCH):
            part = keys[i:i + BATCH]
            if len(part) == BATCH:
                out.append(part)
            elif len(cur) + len(part) <= BATCH:
                cur += part
            else:
                out.append(cur)
                cur = list(part)
    if cur:
        out.append(cur)
    return out


def _json(reply: Any) -> Any:
    text = reply[0] if isinstance(reply, tuple) else reply
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def _asker(llm: Any, f: Family) -> Any:
    def ask(template: Any, values: dict[str, str]) -> Any:
        try:
            return llm.ask(template, values, project=f"subjects:{f.name}", inputs=(f.tokens[0],))
        except ReplayMiss as e:  # a replayed run: at the root, a miss is an unanswered request, not a failure
            log.debug("subjects of %s: %s", f.name, e)
            return None
    return ask


def ways_for(llm: Any, fams: list[Family], concurrency: int = 1, advance: Any = None) -> dict[str, list[dict[str, Any]] | None]:
    """Each family's ways, by its newest token: every diagram assigned or left unsorted; None when
    the proposal failed (no answer, or none that can be read). Two rounds, each `concurrency`
    requests at a time: every family's proposal, then every batch of every way."""

    def propose(f: Family) -> list[list[dict[str, Any]]] | None:
        got = _asker(llm, f)(SUBJECTS_PROPOSE, {"MODEL": f.name, "COUNT": str(len(f.items)), "WAYS": str(WAYS),
                                                "K": str(target(len(f.items))), "OUTLINE": outline(f)})
        if advance:
            advance(1)
        ways = [w for w in ((_json(got) or {}).get("ways") or [])[:WAYS] if isinstance(w, dict)]
        ways = [(w, [s for s in w.get("subjects") or [] if isinstance(s, dict) and s.get("label")]) for w in ways]
        return [{"principle": w.get("principle"), "subjects": subs} for w, subs in ways if len(subs) >= 2] or None

    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        proposed = dict(zip((f.tokens[0] for f in fams), pool.map(propose, fams), strict=True))
    tasks = [(f, n, batch) for f in fams for n in range(len(proposed[f.tokens[0]] or [])) for batch in batches(f)]

    def assign(task: tuple[Family, int, list[str]]) -> dict[str, Any]:
        f, n, batch = task
        subjects = proposed[f.tokens[0]][n]["subjects"]
        listing = "\n".join(f"{i}. {s['label']}: {s.get('holds', '')}" for i, s in enumerate(subjects, 1))
        text = "\n".join(f"{i}. {f.items[key].describe()}" for i, key in enumerate(batch, 1))
        r = _asker(llm, f)(SUBJECTS_ASSIGN, {"SUBJECTS": listing, "DIAGRAMS": text})
        if advance:
            advance(1)
        reply = _json(r) or {}
        return {key: reply.get(str(i)) for i, key in enumerate(batch, 1)}

    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        answers = list(pool.map(assign, tasks))
    assigned: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for (f, n, _), got in zip(tasks, answers, strict=True):
        assigned[f.tokens[0], n].update(got)
    out: dict[str, list[dict[str, Any]] | None] = {}
    for f in fams:
        ways = proposed[f.tokens[0]]
        if ways is None:
            out[f.tokens[0]] = None
            continue
        views = []
        for n, way in enumerate(ways):
            subjects = way["subjects"]
            members: dict[int, list[str]] = defaultdict(list)
            unsorted = []
            for key, v in sorted(assigned[f.tokens[0], n].items()):
                try:
                    g = int(v) - 1
                except (TypeError, ValueError):
                    g = -1
                if 0 <= g < len(subjects):
                    members[g].append(key)
                else:
                    unsorted.append(key)
            views.append({"id": f"ways-{n + 1}", "kind": "llm", "title": str(way["principle"] or f"Way {n + 1}")[:80],
                          "model": llm.cfg.text_model,
                          "subjects": [{"label": str(subjects[g]["label"])[:80],
                                        "holds": str(subjects[g].get("holds", ""))[:300], "diagrams": members[g]}
                                       for g in range(len(subjects)) if members[g]],
                          "unsorted": unsorted})
        out[f.tokens[0]] = views
    return out


def requests(f: Family) -> int:
    """How many requests a family's ways take."""
    return 1 + WAYS * len(batches(f)) if len(f.items) >= MIN_ITEMS else 0


# -- the root file -----------------------------------------------------------------------------------
def entry(f: Family, ways: list[dict[str, Any]] | None, asked: bool) -> dict[str, Any]:
    """A family's record: its views, the default first. `asked`: the LLM was asked for its ways (so
    their absence means the proposal failed, not that the tree has no LLM)."""
    rec: dict[str, Any] = {"name": f.name, "tokens": f.tokens, "signature": f.signature,
                           "diagrams": {key: [f.tokens.index(t) for t in it.versions] for key, it in sorted(f.items.items())},
                           "copies": f.copies}
    if len(f.items) < MIN_ITEMS:
        rec.update(views=[package_view(f)], default="packages", ways="too few diagrams")
        return rec
    views: list[dict[str, Any]] = list(ways or [])
    worst = max((len(v["unsorted"]) / len(f.items) for v in views), default=1.0)
    if not views or worst > UNSORTED_LIMIT:
        views.insert(0, shared_view(f))  # the fallback, first
    views.append(package_view(f))
    rec.update(views=views, default=views[0]["id"],
               ways=("found" if ways and worst == 0 else "incomplete" if ways else "failed" if asked else "not asked"))
    return rec


def load(out: Path) -> dict[str, dict[str, Any]]:
    """The last `subjects.json`, by its families' newest token."""
    try:
        data = json.loads((out / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("format") != FORMAT:
        return {}
    return {rec["tokens"][0]: rec for rec in data.get("families", [])}


def load_topics(out: Path) -> dict[str, Any] | None:
    """The last `subjects.json`'s topics across models, if any."""
    try:
        data = json.loads((out / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("topics") if data.get("format") == FORMAT else None


def summary(out: Path) -> dict[str, Any]:
    """For `status`: how many families, how their ways stand, and how the topics across models do."""
    recs = load(out)
    topics = load_topics(out) or {}
    return {"families": len(recs), **dict(sorted(Counter(r.get("ways") for r in recs.values()).items())),
            **({"topics": topics["ways"]} if topics.get("ways") else {})}


def update(state: Any, out: Path, llm: Any = None, concurrency: int = 1, progress: Progress = QUIET) -> dict[str, Any]:
    """Write `subjects.json`. With a session that has a text model, ask for the ways of each family
    that lacks complete ones; without, keep each unchanged family's record and give others the
    fallback. Returns counts for the run's record."""
    fams = [f for f in families(state, out) if f.items]
    before = load(out)
    can_ask = llm is not None and getattr(llm.cfg, "text_model", None)
    records = []
    todo = []
    for f in fams:
        old = before.get(f.tokens[0])
        same = old is not None and old.get("signature") == f.signature and old.get("tokens") == f.tokens
        if same and (old.get("ways") in ("found", "too few diagrams") or not can_ask):
            records.append(old)
        elif can_ask and len(f.items) >= MIN_ITEMS:
            todo.append(f)
            records.append(None)
        else:
            records.append(entry(f, None, asked=False))
    if todo:
        total = sum(requests(f) for f in todo)
        with progress.phase(f"subjects: {len(todo)} famil{'y' if len(todo) == 1 else 'ies'}", total, "request") as ph:
            found = ways_for(llm, todo, concurrency, ph.advance)
        asked = {f.tokens[0]: entry(f, found[f.tokens[0]], asked=True) for f in todo}
        records = [r if r is not None else asked[f.tokens[0]] for r, f in zip(records, fams, strict=True)]
    from . import topics

    found = topics.update(fams, records, load_topics(out), llm if can_ask else None, concurrency, progress)
    data = {"format": FORMAT, "families": records, "topics": found}
    tmp = out / (FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(out / FILE)
    counts = Counter(r.get("ways") for r in records)
    for r in records:
        if r.get("ways") in ("failed", "incomplete"):
            log.warning("subjects of %s: the LLM's ways %s; %s is shown first until a run completes them", r["name"],
                        "failed" if r["ways"] == "failed" else "left diagrams unsorted", r["views"][0]["title"])
    if found.get("ways") in ("failed", "incomplete"):
        log.warning("topics across models: the LLM's %s; topics by words are shown first until a run completes them",
                    "failed" if found["ways"] == "failed" else "left subjects unsorted")
    return {"families": len(records), **dict(sorted((k, v) for k, v in counts.items() if k)), "topics": found["ways"]}

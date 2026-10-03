"""Versions of one model, found by the element ids they share (plan PV-03).

Two projects are **likely versions** when half or more of their ids are shared (their Jaccard
index), or 80% of the smaller one's when that is at least 50 ids. Projects so linked, directly or
through others (a model growing over many versions), make a group, newest first. **Related**
projects share less, at least 20% of the smaller one's ids and at least 20 ids, as two models
made from one template do. They are listed, not grouped.

Nothing is decided here: the report shows each group, warns where a member has many elements the
newest lacks (a fork, or much deleted since), and suggests a `remove` command for the maintainer
to copy if they agree.
"""

from __future__ import annotations

import csv
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fingerprint import unpack

VERSION_JACCARD = 0.5
VERSION_COVER, VERSION_MIN = 0.8, 50
RELATED_COVER, RELATED_MIN = 0.2, 20
FORK = 0.10  # a member with this share of its ids not in the newest is flagged


@dataclass
class Member:
    sha: str
    name: str
    status: str
    saved: str | None
    saved_raw: str | None
    saved_from: str | None
    elements: int
    paths: list[str]
    shared: float = 1.0  # of its ids, the share the group's newest has too
    only_here: float = 0.0  # of its ids, the share the newest lacks


@dataclass
class Group:
    members: list[Member]  # newest first
    warnings: list[str] = field(default_factory=list)


@dataclass
class Report:
    groups: list[Group]
    related: list[tuple[Member, Member, int, float]]  # (a, b, shared ids, share of the smaller)
    without: list[str]  # names of projects without a fingerprint


def _when(m: Member) -> tuple[int, str]:
    """For ordering newest first: a known time, then a time from the zip's dates, then none."""
    if not m.saved:
        return (0, "")
    return (1 if m.saved_from == "zip" else 2, _utc(m.saved))


def _utc(iso: str) -> str:
    import datetime as dt

    when = dt.datetime.fromisoformat(iso)
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return when.isoformat()


def find(catalog: list[Any], ids: dict[str, bytes], paths: dict[str, list[str]],
         include_removed: bool = False) -> Report:
    """`catalog`: the state's rows (status and fingerprint); `ids`: each content's packed ids."""
    members = {r["sha256"]: Member(r["sha256"], r["name"], r["status"], r["saved"], r["saved_raw"], r["saved_from"],
                                   r["elements"] or 0, paths.get(r["sha256"], []))
               for r in catalog if r["sha256"] in ids and (include_removed or r["status"] != "removed")}
    without = [r["name"] for r in catalog if r["sha256"] not in ids and r["status"] != "removed"]
    sets = {sha: unpack(ids[sha]) for sha in members}
    parent = {sha: sha for sha in members}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    related = []
    shas = sorted(members, key=lambda s: -len(sets[s]))
    for a, b in itertools.combinations(shas, 2):
        sa, sb = sets[a], sets[b]
        if not sa or not sb:
            continue
        shared = len(sa & sb) if len(sa) <= len(sb) else len(sb & sa)
        if not shared:
            continue
        smaller = min(len(sa), len(sb))
        cover, jaccard = shared / smaller, shared / (len(sa) + len(sb) - shared)
        if jaccard >= VERSION_JACCARD or (cover >= VERSION_COVER and shared >= VERSION_MIN):
            parent[root(a)] = root(b)
        elif cover >= RELATED_COVER and shared >= RELATED_MIN:
            related.append((members[a], members[b], shared, cover))
    by_root: dict[str, list[str]] = {}
    for sha in members:
        by_root.setdefault(root(sha), []).append(sha)
    groups = []
    for shas_ in by_root.values():
        if len(shas_) < 2:
            continue
        ms = sorted((members[s] for s in shas_), key=_when, reverse=True)
        newest = sets[ms[0].sha]
        g = Group(ms)
        for m in ms[1:]:
            own = sets[m.sha]
            common = len(own & newest)
            m.shared, m.only_here = common / len(own), 1 - common / len(own)
            if m.only_here >= FORK:
                g.warnings.append(f"{m.name} ({m.sha[:8]}) has {m.only_here:.0%} of its elements that the newest "
                                  "lacks: a fork, or much deleted since")
        if any(not m.saved for m in ms):
            g.warnings.append("some members have no save time, so their order is a guess")
        elif any(m.saved_from == "zip" for m in ms):
            g.warnings.append("some save times are the dates inside the zip, not Cameo's own record")
        groups.append(g)
    groups.sort(key=lambda g: (g.members[0].name.lower(), g.members[0].sha))
    related = [r for r in related if root(r[0].sha) != root(r[1].sha)]
    return Report(groups, related, without)


def _row(m: Member, newest: bool) -> str:
    when = m.saved_raw or "no save time"
    if m.saved_from == "zip":
        when += " (zip dates)"
    share = "newest" if newest else f"{m.shared:.0%} shared, {m.only_here:.0%} only here"
    where = "; ".join(m.paths[:3]) + (f"; and {len(m.paths) - 3} more" if len(m.paths) > 3 else "")
    status = "" if m.status == "written" else f" [{m.status}]"
    return f"| `{m.sha[:8]}` | {m.name}{status} | {when} | {m.elements:,} | {share} | {where} |"


def render(report: Report, out: Path) -> str:
    lines = ["# Versions of the same model", "",
             f"{len(report.groups)} group(s) of likely versions, newest first in each, by Cameo's save time. "
             "Nothing has been removed: check each group, then copy the command at the end if you agree.", ""]
    for k, g in enumerate(report.groups, 1):
        lines += [f"## Group {k}: {g.members[0].name}", "",
                  "| Token | Project | Saved | Elements | Ids | Found at |", "|---|---|---|---|---|---|"]
        lines += [_row(m, i == 0) for i, m in enumerate(g.members)]
        lines += [""] + [f"- **Check:** {w}" for w in g.warnings] + ([""] if g.warnings else [])
    if report.related:
        lines += ["## Related, not grouped", "",
                  "These share some elements, as models made from one template, or from parts of one model, do.", ""]
        lines += [f"- {a.name} (`{a.sha[:8]}`) and {b.name} (`{b.sha[:8]}`): {n:,} elements, {c:.0%} of the smaller"
                  for a, b, n, c in report.related]
        lines.append("")
    if report.without:
        lines += [f"Not compared, without a fingerprint (run `cameo-ingest scan -o {out}`): "
                  + ", ".join(report.without), ""]
    clean = [m for g in report.groups if not g.warnings for m in g.members[1:]]
    checked = [m for g in report.groups if g.warnings for m in g.members[1:]]
    if clean:
        lines += ["## To keep only the newest of each group without warnings", "", "```sh",
                  f"cameo-ingest remove -o {out} " + " ".join(m.sha[:12] for m in clean), "```", ""]
    if checked:
        lines += ["Groups with warnings are left out of that command. Their older members, once checked: "
                  + " ".join(f"`{m.sha[:12]}`" for m in checked), ""]
    return "\n".join(lines)


def write_csv(report: Report, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "rank", "token", "name", "status", "saved", "saved_from", "elements", "shared_with_newest",
                    "only_here", "paths", "warnings"])
        for k, g in enumerate(report.groups, 1):
            for i, m in enumerate(g.members):
                w.writerow([k, i + 1, f"sha256:{m.sha}", m.name, m.status, m.saved_raw or "", m.saved_from or "",
                            m.elements, f"{m.shared:.3f}", f"{m.only_here:.3f}", "; ".join(m.paths),
                            " | ".join(g.warnings) if i == 0 else ""])

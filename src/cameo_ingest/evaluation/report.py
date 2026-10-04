"""What a retrieval run reports (AR-020R1): per question and system, the measures; the rankings'
tops, for inspection; and `report.md`, the measures' means by question group, with confidence
intervals, and the questions each system missed. Two runs are compared question by question
(`compare`), as every release check does."""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from dataclasses import dataclass

from .grading import Graded
from .harness import Unit, group_measures, mean_ci, measures, paired_ci
from .records import Run

MARK = " \\*"  # a significant change, in Markdown
MEASURES = ("hit@1", "hit@5", "hit@10", "hit@20", "mrr@10", "ndcg@10", "coverage@10", "complete@10")


def per_question(systems: dict[str, list[list[int]]], questions: list[dict], windows: list[Unit],
                 graded: list[Graded]) -> tuple[dict[str, list[dict]], list[dict]]:
    """(each system's measures per question, each question's top 10 per system)."""
    results: dict[str, list[dict]] = {}
    rankings = []
    for name, ranked in systems.items():
        per_q = []
        for q, ranking, (g, parts, covers) in zip(questions, ranked, graded, strict=True):
            per_q.append({"id": q["id"], "style": q["style"], "difficulty": q.get("difficulty"),
                          "project_name": q.get("project_name"), **measures(ranking, g),
                          **group_measures(ranking, covers, parts)})
            rankings.append({"system": name, "question": q["id"], "text": q["question"],
                             "top": [{"unit": windows[j].id, "kind": windows[j].kind, "grade": g.get(j, 0),
                                      "text": windows[j].text[:200]} for j in ranking[:10]]})
        results[name] = per_q
    return results, rankings


def rows(results: dict[str, list[dict]]) -> list[dict]:
    """Every measure, one row per system and question, for analysis."""
    return [{"system": name, **r} for name, per_q in results.items() for r in per_q]


def render(results: dict[str, list[dict]], questions: list[dict], run: Run, units: int) -> str:
    """report.md: the means for all questions, then by style, difficulty and project where they
    differ; then the questions missed in the top 10."""
    styles = Counter(q["style"] for q in questions)
    lines = [f"# Retrieval: {run.questions} questions on {run.tree}", "",
             (f"{units:,} chunks, windows of {run.window} tokens with {run.overlap} of overlap; "
              f"{len(questions)} questions ({', '.join(f'{n} {s}' for s, n in sorted(styles.items()))})."), ""]
    groups: list[tuple[str, str | None]] = [("all", None)]
    for field in ("style", "difficulty", "project_name"):
        values = sorted({str(q.get(field)) for q in questions if q.get(field)})
        groups += [(v, field) for v in values] if len(values) > 1 else []
    for group, field in groups:
        lines += [f"## {group.capitalize() if field != 'project_name' else group} questions", "",
                  "| System | " + " | ".join(MEASURES) + " |", "|---|" + "---|" * len(MEASURES)]
        for name, per_q in results.items():
            selected = [r for r in per_q if field is None or str(r.get(field)) == group]
            cells = []
            for mname in MEASURES:
                mean, lo, hi = mean_ci([r[mname] for r in selected])
                cells.append(f"{mean:.2f} ({lo:.2f}–{hi:.2f})" if mname in ("hit@10", "mrr@10") else f"{mean:.2f}")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    misses = defaultdict(list)
    for name, per_q in results.items():
        for r in per_q:
            if not r["hit@10"]:
                misses[r["id"]].append(name)
    lines += ["## Questions missed in the top 10", ""] + [
        f"- {qid}: {', '.join(names)}" for qid, names in sorted(misses.items())] + [""]
    return "\n".join(lines)


@dataclass(frozen=True)
class Change:
    """A measure's mean in two runs, and its change with a paired 95% interval."""

    measure: str
    before: float
    after: float
    change: float
    lo: float
    hi: float

    @property
    def significant(self) -> bool:
        return self.lo > 0 or self.hi < 0


@dataclass
class Comparison:
    """Two runs' measures, system by system, over the questions both asked."""

    questions: int  # asked in both
    only_before: int
    only_after: int
    rounds: int
    changes: dict[str, list[Change]] = dataclasses.field(default_factory=dict)  # by system
    found: dict[str, tuple[list[str], list[str]]] = dataclasses.field(default_factory=dict)  # hit@10 lost, gained

    def significant(self) -> list[tuple[str, Change]]:
        return [(name, c) for name, cs in self.changes.items() for c in cs if c.significant]


def compare(before: list[dict], after: list[dict], rounds: int = 4000) -> Comparison:
    """Two runs' `per_question` rows, paired by question for each system both ran: the change in
    each measure's mean, with a paired bootstrap interval. Questions asked in one run only are
    counted and left out."""
    def by_system(rows: list[dict]) -> dict[str, dict[str, dict]]:
        out: dict[str, dict[str, dict]] = defaultdict(dict)
        for r in rows:
            out[r["system"]][r["id"]] = r
        return out

    a, b = by_system(before), by_system(after)
    ids_a = {q for rs in a.values() for q in rs}
    ids_b = {q for rs in b.values() for q in rs}
    shared = sorted(ids_a & ids_b)
    out = Comparison(len(shared), len(ids_a - ids_b), len(ids_b - ids_a), rounds)
    for name in [n for n in a if n in b]:
        ids = [q for q in shared if q in a[name] and q in b[name]]
        changes = []
        for m in MEASURES:
            if not all(m in a[name][q] and m in b[name][q] for q in ids):
                continue
            xs, ys = [a[name][q][m] for q in ids], [b[name][q][m] for q in ids]
            change, lo, hi = paired_ci(xs, ys, rounds)
            changes.append(Change(m, sum(xs) / len(xs) if ids else 0.0, sum(ys) / len(ys) if ids else 0.0,
                                  change, lo, hi))
        out.changes[name] = changes
        out.found[name] = ([q for q in ids if a[name][q]["hit@10"] and not b[name][q]["hit@10"]],
                           [q for q in ids if b[name][q]["hit@10"] and not a[name][q]["hit@10"]])
    return out


def render_comparison(c: Comparison, before: str, after: str) -> str:
    """The comparison as Markdown: a table per system, then the questions found in one run's top
    10 only."""
    unpaired = (f" ({c.only_before} asked only before, {c.only_after} only after, left out)"
                if c.only_before or c.only_after else "")
    lines = [f"# Retrieval compared: {before} → {after}", "",
             (f"{c.questions} questions in both{unpaired}; paired bootstrap over the questions, "
              f"{c.rounds:,} rounds, 95%. \\* marks a change whose interval excludes zero."), "",
             f"**Significant changes:** {len(c.significant()) or 'none'}.", ""]
    for name, changes in c.changes.items():
        lines += [f"## {name}", "", "| Measure | Before | After | Change (95% interval) |", "|---|---|---|---|"]
        lines += [f"| {x.measure} | {x.before:.3f} | {x.after:.3f} | {x.change:+.3f} ({x.lo:+.3f} to {x.hi:+.3f})"
                  f"{MARK if x.significant else ''} |" for x in changes]
        lost, gained = c.found[name]
        lines += ["", (f"In the top 10 only before: {', '.join(lost) or 'none'}. "
                       f"Only after: {', '.join(gained) or 'none'}."), ""]
    return "\n".join(lines)

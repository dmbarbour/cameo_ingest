"""What a retrieval run reports (AR-020R1): per question and system, the measures; the rankings'
tops, for inspection; and `report.md`, the measures' means by question group, with confidence
intervals, and the questions each system missed."""

from __future__ import annotations

from collections import Counter, defaultdict

from .grading import Graded
from .harness import Unit, group_measures, mean_ci, measures
from .records import Run

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

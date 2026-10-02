"""Questions about the real samples whose answers follow from the model's structure (plan RE-04).

Each template reads a project's tables (requirements, relationships, elements) and asks about
an element by its name or id, so the questions are literal: they share words with their
answers. The answers are graded by construction: `answers` are the elements whose chunk
answers the question (grade 2), `related` those whose chunk helps (grade 1).

Questions are drawn evenly from each project (`per_project` per template), so that TMT, with
most of the chunks, doesn't make most of the questions, and names that several elements share
are skipped as ambiguous.
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..llm import EnrichmentSession
from ..plain import plain
from ..prompts import Slot, Template
from ..text import DOORS_ID
from .fiction import is_fictional

csv.field_size_limit(1 << 30)


def _rows(project: Path, table: str) -> list[dict]:
    path = project / "tables" / f"{table}.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def structural(tree: Path, per_project: int = 5, seed: int = 1) -> list[dict]:
    """Questions for every project of the tree but the fictional ones, which have questions of
    their own."""
    manifest = json.loads((tree / "manifest.json").read_text())
    out: list[dict] = []
    for p in manifest["projects"]:
        qs = _project_questions(p["name"], tree / p["dir"], per_project, seed)
        out += [q for q in qs if not is_fictional(q["answers"][0])]
    return out


def _project_questions(name: str, project: Path, per_project: int, seed: int) -> list[dict]:
    out: list[dict] = []
    token = f"sha256:{project.name}"
    rng = random.Random(f"{seed}:{project.name}")
    elements = {r["id"]: r for r in _rows(project, "elements")}
    reqs = _rows(project, "requirements")
    rels = _rows(project, "relationships")
    names = Counter(r["name"] for r in elements.values() if r["name"])

    def named(el_id: str) -> str | None:
        """The element's name, if no other element in the project shares it."""
        name = (elements.get(el_id) or {}).get("name") or ""
        return name if name and names[name] == 1 and len(name) <= 80 else None

    def add(template: str, question: str, answers: list[str], related: list[str]) -> None:
        out.append({"id": f"{name}:{template}:{answers[0]}", "rule": "element", "template": template, "category": template,
                    "style": "literal", "project": token, "question": question, "answers": answers,
                    "related": related})

    def draw(items: list, k: int = per_project) -> list:
        items = sorted(items, key=str)
        return rng.sample(items, min(k, len(items)))

    # Requirements by id: a bracketed id at the start of the text (DOORS), or else the Id tag.
    by_id = []
    for r in reqs:
        m = DOORS_ID.match(r["text"] or "")
        rid = m.group(1) if m else r["req_id"]
        if rid and len(r["text"] or "") > 40 and re.search(r"[A-Za-z]", rid):
            by_id.append((rid, r["id"]))
    counts = Counter(rid for rid, _ in by_id)
    for rid, el in draw([x for x in by_id if counts[x[0]] == 1]):
        add("requirement-by-id", f"What does requirement {rid} state?", [el], [])

    # Relationships, grouped by the element they lead to.
    to: dict[tuple[str, str], list[str]] = defaultdict(list)  # (kind, target) -> sources
    for r in rels:
        to[(r["kind"].lower(), r["target_id"])].append(r["source_id"])
    for kind, template, ask in (("derivereqt", "derivation", "Which requirements are derived from {}?"),
                                ("satisfy", "satisfaction", "Which elements satisfy the requirement {}?")):
        cands = [(t, srcs) for (k, t), srcs in to.items() if k == kind and named(t)]
        for target, sources in draw(cands):
            add(template, ask.format(named(target)), [target], sorted(set(sources)))
    allocs = [(r["source_id"], r["target_id"]) for r in rels
              if r["kind"].lower() == "allocate" and named(r["source_id"]) and named(r["target_id"])]
    for source, target in draw(allocs):
        add("allocation", f"What is {named(source)} allocated to?", [source], [target])

    # Elements with documentation of their own, asked about by name and package.
    documented = [e for e in elements.values()
                  if len(e["documentation"] or "") >= 80 and named(e["id"]) and "::" in e["qualified_name"]
                  and e["type"] not in ("uml:Package", "uml:Model", "uml:Diagram", "uml:Comment")]
    for e in draw(documented):
        package = e["qualified_name"].split("::")[-2]
        where = f" in {package}" if package.lower() != e["name"].lower() else ""
        add("lookup", f"What is {e['name']}{where}?", [e["id"]], [])
    return out


# -- natural questions, written by a strong model from a sampled chunk ----------------------------
QUESTION_WRITER = Template(
    id="eval-question-writer",
    version=2,
    purpose="Writes one natural question that a sampled chunk answers, for the retrieval evaluation (plan RE-04).",
    text=(
        "Below is a passage from the documentation of a systems engineering model (UML/SysML, authored in "
        "Cameo), as a search index holds it. Write one question that a systems engineer might ask and that "
        "this passage answers. Ask about its substance (what something does, requires, is made of, or connects "
        "to), not about its formatting, ids or links. Make the question specific enough to have one answer in "
        "a library of many unrelated models: say which system, subsystem or topic it is about, though a "
        "description will do. Where a description would do, describe things rather than copying their exact "
        "names, as someone who half-remembers them would. Then quote the shortest part of the passage, word "
        "for word, that answers the question.\n\n"
        "Reply with JSON only: {\"question\": \"...\", \"quote\": \"...\"}. If the passage holds nothing worth "
        "asking about, or is about unnamed elements, tool or profile settings (stereotype customizations, "
        "auxiliary resources, diagram or table configuration), reply {\"question\": \"\", \"quote\": \"\"}.\n\n"
        "Kind of passage: {{KIND}}\n---\n{{PASSAGE}}"
    ),
    slots=(
        Slot("KIND", "text", "the chunk's kind, such as requirement, element or generated:summary."),
        Slot("PASSAGE", "text", "the chunk's text, cut at 6,000 characters."),
    ),
)


def sample_chunks(tree: Path, per_project: int = 6, seed: int = 1) -> list[dict]:
    """Chunks to write questions from: up to `per_project` from each project, of the kinds that
    describe something (not ledgers or project overviews), at least 300 characters long."""
    by_project: dict[str, list[dict]] = defaultdict(list)
    for line in (tree / "chunks.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        m = c["metadata"]
        if (m["kind"].startswith(("ledger", "project")) or len(c["text"]) < 300 or not m.get("content")
                or is_fictional(m.get("element_id"))):
            continue
        by_project[m["content"]].append(c)
    rng = random.Random(seed)
    out = []
    for token in sorted(by_project):
        chunks = sorted(by_project[token], key=lambda c: c["id"])
        out += rng.sample(chunks, min(per_project, len(chunks)))
    return out


def natural(tree: Path, llm: EnrichmentSession, per_project: int = 6, seed: int = 1,
            concurrency: int = 6) -> list[dict]:
    """One question per sampled chunk, written by `llm`'s text model. A question is kept only if
    its quote is found in the chunk: the chunk is then its known answer (`answer_chunks`)."""
    chunks = sample_chunks(tree, per_project, seed)

    def ask(c: dict) -> dict | None:
        res = llm.ask(QUESTION_WRITER, {"KIND": c["metadata"]["kind"], "PASSAGE": plain(c["text"])[:6000]},
                      project=c["metadata"]["content"], inputs=(c["id"],))
        if res is None:
            return None
        m = re.search(r"\{.*\}", res[0], re.DOTALL)
        try:
            reply = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return None
        question, quote = (reply.get("question") or "").strip(), (reply.get("quote") or "").strip()
        if not question or len(quote) < 8 or " ".join(quote.split()) not in " ".join(plain(c["text"]).split()):
            return None
        meta = c["metadata"]
        return {"id": f"llm:{c['id']}", "rule": "source", "template": "llm", "category": meta["kind"], "style": "natural",
                "project": meta["content"], "question": question, "quote": quote,
                "answers": [], "related": [], "answer_chunks": [c["id"]], "source_kind": meta["kind"],
                "source_element": meta.get("element_id")}  # for corpora whose chunks differ (another chunk style)

    with ThreadPoolExecutor(concurrency) as pool:
        return [q for q in pool.map(ask, chunks) if q is not None]

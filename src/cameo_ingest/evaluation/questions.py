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


# -- Where something is described (plan GS-08) ---------------------------------------------------
WHERE_WRITER = Template(
    id="eval-where-writer",
    version=1,
    purpose="Writes two questions asking where a package, diagram or behavior is described, a literal one and a "
            "paraphrase, for the retrieval evaluation (plan GS-08).",
    text=(
        "Below is a part of a systems engineering model (UML/SysML, authored in Cameo), as a search index holds its "
        "extracted text: a {{KIND}} of the model in {{PROJECT}}. People search a library of many unrelated models for "
        "the part of a model that covers a topic. Write two questions that someone would ask to find this {{KIND}}:\n"
        "1. literal: in the model's own terms, but without this {{KIND}}'s exact name;\n"
        "2. paraphrase: in everyday words, with none of the model's names, identifiers or exact values.\n"
        "Each asks where something is covered or described (\"Where is ... described?\", \"Which part of ... covers "
        "...?\"), not for a single fact, and says which system it is about, though a description will do. Base them "
        "on what the text shows; if it shows too little to tell what this {{KIND}} covers, say so.\n\n"
        "Reply with JSON only: {\"literal\": \"...\", \"paraphrase\": \"...\"}, or {\"skip\": \"why\"}.\n\n"
        "---\n{{PASSAGE}}"
    ),
    slots=(
        Slot("KIND", "text", "'package', 'diagram', 'activity' or 'state machine'."),
        Slot("PROJECT", "text", "the project's file name, without its extension."),
        Slot("PASSAGE", "text", "the target's extracted chunk (its first part, or all parts), cut at 6,000 "
                                "characters; never generated text."),
    ),
)
_BEHAVIORS = {"uml:Activity": "activity", "uml:StateMachine": "state machine"}
_SHAPES = re.compile(r"^Shapes \((\d+)\)", re.MULTILINE)


def where_targets(tree: Path, fiction: int = 20, samples: int = 40, seed: int = 1) -> list[dict]:
    """What questions about where something is described can be about (plan GS-08), from the
    extracted chunks alone (an item's own and its details): packages with 5 members or more, diagrams with 3 shapes or more,
    activities and state machines with a diagram. `fiction` from the fiction, `samples` from the
    rest, at most 4 a project and two thirds of them undocumented. Each with the elements whose
    chunks answer it (itself and its diagrams, or a diagram's behavior) and those that relate (its
    owner), and its text for the writer."""
    texts: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, dict] = {}
    by_qn: dict[tuple[str, str], list[str]] = defaultdict(list)
    diagrams_of: dict[tuple[str, str], list[str]] = defaultdict(list)
    for line in (tree / "chunks.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        m = c["metadata"]
        el, qn, content = m.get("element_id"), m.get("qualified_name"), m.get("content")
        kind = m["kind"].removesuffix(":details")  # a large item's members and values are in its details
        if kind not in ("package", "diagram", "element") or not el or not qn or not content:
            continue
        texts[el].append(c["text"])
        if el not in meta and kind == m["kind"]:
            meta[el] = m
            by_qn[(content, qn)].append(el)
            if kind == "diagram":
                diagrams_of[(content, qn.rsplit("::", 1)[0])].append(el)
    candidates = []
    for el, m in meta.items():
        content, qn, text = m["content"], m["qualified_name"], "\n\n".join(texts[el])
        owner = qn.rsplit("::", 1)[0] if "::" in qn else None
        parent = by_qn.get((content, owner), []) if owner else []
        if m["kind"] == "package":
            kind = "package"
            members = text.split("Members:", 1)[1] if "Members:" in text else ""
            if sum(line.startswith("- ") for line in members.splitlines()) < 5:
                continue
            answers, related = [el, *diagrams_of[(content, qn)]], parent
        elif m["kind"] == "diagram":
            kind = "diagram"
            shapes = _SHAPES.search(text)
            if not shapes or int(shapes.group(1)) < 3:
                continue
            behavior = [p for p in parent if meta[p].get("element_type") in _BEHAVIORS]
            answers, related = [el, *behavior], [p for p in parent if p not in behavior]
        elif m.get("element_type") in _BEHAVIORS and diagrams_of[(content, qn)]:
            kind = _BEHAVIORS[m["element_type"]]
            answers, related = [el, *diagrams_of[(content, qn)]], parent
        else:
            continue
        candidates.append({"element_id": el, "kind": kind, "content": content, "project": m.get("project"),
                           "qualified_name": qn, "documented": "\nDocumentation:" in text, "text": text,
                           "answers": list(dict.fromkeys(answers)), "related": list(dict.fromkeys(related)),
                           "origin": "fiction" if is_fictional(el) else "samples"})
    rng = random.Random(seed)
    candidates.sort(key=lambda t: t["element_id"])
    rng.shuffle(candidates)
    out = [t for t in candidates if t["origin"] == "fiction"][:fiction]
    per_project: Counter[str] = Counter()
    undocumented = round(samples * 2 / 3)
    for want_doc, quota in ((False, undocumented), (True, samples - undocumented)):
        taken = 0
        for t in candidates:
            if taken == quota:
                break
            if t["origin"] == "samples" and t["documented"] == want_doc and per_project[t["content"]] < 4:
                out.append(t)
                per_project[t["content"]] += 1
                taken += 1
    return out


def where_questions(targets: list[dict], llm: EnrichmentSession, writer: str, concurrency: int = 6) -> list[dict]:
    """Two questions per target from one writer (`llm`'s text model): literal and paraphrase,
    graded by element (rule `element`). A target the writer skips gets none."""
    short = re.sub(r"[^a-z0-9]+", "-", writer.split("/")[-1].lower()).strip("-")

    def ask(t: dict) -> list[dict]:
        project = (t["project"] or "").rsplit(".", 1)[0]
        res = llm.ask(WHERE_WRITER, {"KIND": t["kind"], "PROJECT": project, "PASSAGE": plain(t["text"])[:6000]},
                      project=t["content"], inputs=(t["element_id"],))
        m = re.search(r"\{.*\}", res[0], re.DOTALL) if res else None
        try:
            reply = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return []
        out = []
        for style in ("literal", "paraphrase"):
            text = str(reply.get(style) or "").strip()
            if text:
                out.append({"id": f"wq-{short}-{t['element_id']}-{style}", "rule": "element", "fact": f"wq-{t['element_id']}",
                            "style": style, "category": "where", "difficulty": "medium", "question": text,
                            "answers": t["answers"], "related": t["related"], "evidence": [], "prefix": "",
                            "project_name": project, "writer": writer, "origin": t["origin"],
                            "documented": t["documented"], "target_kind": t["kind"],
                            "target": t["qualified_name"]})
        return out

    with ThreadPoolExecutor(concurrency) as pool:
        return [q for qs in pool.map(ask, targets) for q in qs]

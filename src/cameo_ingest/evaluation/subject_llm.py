"""Splits into subjects with the tree's text model (plan SB-05).

- **L1** labels G's groups: the model reads each group's diagrams and names its subject; groups it
  names alike are merged. The diagrams stay where G put them.
- **L2** proposes ways to organize a model: from an outline (its packages, with their diagram
  counts, and example diagrams), the model proposes `WAYS` ways, each on its own principle, of
  about k subjects, each with a label and what it holds; then every diagram is assigned to one
  subject of each way, `BATCH` diagrams a request. The panel judges the ways (the maintainer:
  "propose a few viable splits and ask which one a human would find 'natural'").

The proposer is the tree's text model, as for users; the judges are other models.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..llm import EnrichmentSession
from ..prompts import Slot, Template
from .subject_judges import describe

WAYS = 3
BATCH = 30
SHOWN = 12  # diagrams shown for a group (L1)
EXAMPLES = 60  # example diagrams in an outline (L2)

LABEL_GROUPS = Template(
    id="eval-subjects-label-groups", version=1,
    purpose="L1 of plan SB: name each group of a model's diagrams by its subject.",
    text=("Below are groups of diagrams from one systems engineering model (UML/SysML, authored in Cameo), named "
          "{{MODEL}}. The groups were found by which model elements the diagrams show. For each group, give a short "
          "label, 2 to 5 words, naming its subject, as a systems engineer browsing the model would want it named. "
          "Name the subject matter (what the diagrams are about), not the kind of diagram. If two groups are about "
          "the same subject, give them the same label.\n\n{{GROUPS}}\n\n"
          "Reply with JSON only: {\"labels\": {\"1\": \"label\", \"2\": \"label\", ...}}."),
    slots=(Slot("MODEL", "text", "the model's name."),
           Slot("GROUPS", "text", "the groups, numbered: each with its size and some diagrams.")),
)

PROPOSE = Template(
    id="eval-subjects-propose", version=1,
    purpose="L2 of plan SB: propose ways to organize a model's diagrams into subjects.",
    text=("Below is an outline of one systems engineering model (UML/SysML, authored in Cameo), named {{MODEL}}, "
          "with {{COUNT}} diagrams: its packages, with how many diagrams each holds, and example diagrams. A person "
          "wants to discover the different things this model covers. Propose {{WAYS}} different ways to organize its "
          "diagrams into about {{K}} subjects. Each way should follow its own principle (for example, by part of the "
          "system, by engineering activity, or by kind of concern), and every diagram should fit one subject of "
          "each way. Give each subject a label of 2 to 5 words and one sentence on what it holds.\n\n{{OUTLINE}}\n\n"
          "Reply with JSON only: {\"ways\": [{\"principle\": \"...\", \"subjects\": [{\"label\": \"...\", "
          "\"holds\": \"...\"}, ...]}, ...]}."),
    slots=(Slot("MODEL", "text", "the model's name."), Slot("COUNT", "text", "the number of diagrams."),
           Slot("WAYS", "text", "how many ways to propose."), Slot("K", "text", "about how many subjects."),
           Slot("OUTLINE", "text", "the packages with their diagram counts, and example diagrams.")),
)

ASSIGN = Template(
    id="eval-subjects-assign", version=1,
    purpose="L2 of plan SB: put each of a batch of diagrams in one of a way's subjects.",
    text=("A systems engineering model's diagrams are being organized into these subjects:\n{{SUBJECTS}}\n\n"
          "Put each diagram below in the one subject it fits best.\n\n{{DIAGRAMS}}\n\n"
          "Reply with JSON only, the subject's number for every diagram's number: {\"1\": 3, \"2\": 1, ...}."),
    slots=(Slot("SUBJECTS", "text", "the subjects, numbered: label and what each holds."),
           Slot("DIAGRAMS", "text", "a batch of diagrams, numbered: name, owner, kind, about.")),
)


def _json(reply: str | None) -> Any:
    if not reply:
        return None
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def label_groups(llm: EnrichmentSession, rec: dict[str, Any], split: str = "G") -> dict[str, Any]:
    """L1: `split`'s groups, labelled by the model, those labelled alike merged."""
    s = rec["splits"][split]
    order = sorted(s["groups"], key=lambda g: -len(s["groups"][g]))
    text = []
    for i, g in enumerate(order, 1):
        members = sorted(s["groups"][g])
        shown = "\n".join(f"   - {describe(rec['items'][k])[:160]}" for k in members[:SHOWN])
        text.append(f"{i}. {len(members)} diagrams:\n{shown}" + (f"\n   - … {len(members) - SHOWN} more"
                                                                   if len(members) > SHOWN else ""))
    res = llm.ask(LABEL_GROUPS, {"MODEL": rec["family"], "GROUPS": "\n".join(text)}, project="study:subjects",
                  inputs=(rec["family"],))
    labels = (_json(res[0] if res else None) or {}).get("labels") or {}
    named: dict[str, list[str]] = {}
    for i, g in enumerate(order, 1):
        lab = str(labels.get(str(i)) or f"(unlabelled {i})").strip()
        named.setdefault(lab.lower(), []).append(g)
    groups, out_labels = {}, {}
    for n, (lab, gs) in enumerate(named.items()):
        groups[str(n)] = sorted(k for g in gs for k in s["groups"][g])
        out_labels[str(n)] = str(labels.get(str(order.index(gs[0]) + 1)) or lab)
    return {"groups": groups, "labels": out_labels, "labels_heldout": out_labels}


def outline(rec: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for it in rec["items"].values():
        path = it["package"] or "(the model's root)"
        parts = path.split("::")
        for depth in range(1, min(len(parts), 3) + 1):
            p = "::".join(parts[:depth])
            counts[p] = counts.get(p, 0) + 1
    lines = ["Packages (diagrams):"] + [f"- {p} ({n})" for p, n in sorted(counts.items())][:80]
    keys = sorted(rec["items"])
    step = max(1, len(keys) // EXAMPLES)
    lines += ["", "Example diagrams:"] + [f"- {describe(rec['items'][k])[:160]}" for k in keys[::step][:EXAMPLES]]
    return "\n".join(lines)


def propose(llm: EnrichmentSession, rec: dict[str, Any], concurrency: int = 8) -> dict[str, dict[str, Any]]:
    """L2: the model's ways, each with every diagram assigned; named L2a, L2b, ..."""
    res = llm.ask(PROPOSE, {"MODEL": rec["family"], "COUNT": str(len(rec["items"])), "WAYS": str(WAYS),
                            "K": str(rec["k"]), "OUTLINE": outline(rec)}, project="study:subjects",
                  inputs=(rec["family"],))
    ways = (_json(res[0] if res else None) or {}).get("ways") or []
    out = {}
    keys = sorted(rec["items"])
    for w, way in enumerate(ways[:WAYS]):
        subjects = [s for s in way.get("subjects") or [] if s.get("label")]
        if len(subjects) < 2:
            continue
        listing = "\n".join(f"{i}. {s['label']}: {s.get('holds', '')}" for i, s in enumerate(subjects, 1))
        batches = [keys[i:i + BATCH] for i in range(0, len(keys), BATCH)]

        def one(batch: list[str], listing: str = listing) -> dict[str, Any]:
            text = "\n".join(f"{i}. {describe(rec['items'][k])[:200]}" for i, k in enumerate(batch, 1))
            r = llm.ask(ASSIGN, {"SUBJECTS": listing, "DIAGRAMS": text}, project="study:subjects",
                        inputs=(rec["family"],))
            got = _json(r[0] if r else None) or {}
            return {k: got.get(str(i)) for i, k in enumerate(batch, 1)}

        with ThreadPoolExecutor(concurrency) as pool:
            assigned = {k: v for part in pool.map(one, batches) for k, v in part.items()}
        groups: dict[str, list[str]] = {}
        labels = {}
        for k, v in assigned.items():
            try:
                g = int(v) - 1
                ok = 0 <= g < len(subjects)
            except (TypeError, ValueError):
                ok = False
            gid = str(g) if ok else "unassigned"
            groups.setdefault(gid, []).append(k)
            labels[gid] = subjects[g]["label"] if ok else "(not assigned)"
        out[f"L2{'abc'[w]}"] = {"groups": {g: sorted(v) for g, v in groups.items()}, "labels": labels,
                                "labels_heldout": labels, "principle": way.get("principle", ""),
                                "unassigned": len(groups.get("unassigned", []))}
    return out

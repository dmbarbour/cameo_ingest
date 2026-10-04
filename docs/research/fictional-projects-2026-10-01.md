# Fictional projects: what they found, and retrieval graded by construction

- **Date:** 2026-10-01
- **For:** plan step RE-10 (decision 13) in `docs/archive/plans/retrieval-evaluation-2026-09-30.md`
- **What:** four invented Cameo projects, of rising size and difficulty, with 178 questions
  whose answers are known by construction. They serve as test inputs that are ours to share,
  and as a gold standard for retrieval that needs no judges and no spot checks.

## The projects

| Project | Elements (ids) | Diagrams | Chunks (plain) | Facts | What makes it hard |
|---|---|---|---|---|---|
| Ashgrove Library Book Return Kiosk | 186 | 5 | 49 | 11 | Little: a small model, plain facts |
| Riverbend Water Treatment Works | 792 | 10 | 171 | 26 | A custom profile's tagged values; seven turbidimeters with different limits; requirements imported from DOORS; instances; a state machine's guards; a constraint block; allocations |
| Ferrous Valley Level Crossing | 545 | 11 | 134 | 22 | Two variants whose blocks share their names and differ in their figures; traceability three levels deep; a hazard log; a fact found only in a diagram note |
| Port Calder Traffic Signal System | 5,097 | 28 | 604 | 33 | 150 intersections on twelve corridors, many with near-duplicate names; 130 DOORS-style requirements; a diagram of 150 shapes; timing plans as instances |

**How they are built:**
- **The builder:** `cameo_ingest.evaluation.fiction` writes the XMI and the diagram layouts as
  Cameo does. Signal events are left unnamed and guards are expressions, as in the samples.
- **The questions:** each fact is asked literally (with the model's names) and as a paraphrase.
  - **Tags:** each fact is tagged by category (lookup, parameter, tagged value, instance,
    behaviour, trace, multi-hop, near-duplicate, requirement by id, note) and by a difficulty
    guessed in advance.
- **The answer key:**
  - **Evidence:** each question names its answering elements, and the phrase their chunks hold.
    Where the two ends of a relationship read differently, it gives a phrase per element.
  - **Checked by the tests,** in both chunk styles: the phrase is in an answering element's
    chunks, and in no chunk of an unrelated element (`tests/test_fiction.py`).
- **Grading is strict:** only a window that holds the fact answers (grade 2). A window of an
  answering element without the fact is graded 1.

## What they found in the ingest

Writing the projects the way Cameo stores models turned up three gaps, all of which also hit
the real samples. All three are fixed (0.5.1):
- **Transitions lost their triggers, and flows their guards.** Cameo leaves signal events
  unnamed, so a trigger read as a bare "Trigger"; a guard held as an expression showed no text.
  - **Scale:** 227 triggers and over 200 guards in the samples' pages.
  - **Now:** they read as UML writes them ("Idle → Accepting — Item Detected",
    "[residual below 0.8 mg/L]"), in member lists and on diagram links.
- **Unnamed requirements read "(Class)".** Requirements imported from DOORS have no name.
  - **Scale:** 11,677 "(Class)" labels in the samples' pages, in relationship lines, links and
    legends.
  - **Now:** they read by their id and the start of their text, and their sections are so titled.
- **Diagram notes were cut short or lost.** A note owned by a package and annotating an element
  appeared only in diagram legends, cut at 80 characters.
  - **Scale:** 828 notes in the samples, 484 of them longer than that.
  - **Now:** each element's section lists the notes about it in full.

## Retrieval

**The setup:**
- **The fiction:** the four projects were ingested with LLM enrichment (178 requests), in each
  chunk style.
- **The distractors:** each style's fiction was indexed beside the full corpus of the same style
  (`out/all-plain2` or `out/all`): 35,476 and 29,199 chunks.
- **The rest as before:** 512-token windows with 64 of overlap, and the same models
  (`scripts/retrieval_eval.py`, `out/eval/retrieval-fiction-{plain,markdown}`).
- **Grading:** strict, by construction.

**All 178 questions:** hits in the top 1 and top 10, MRR at 10, and the change in MRR with its
95% interval (paired bootstrap).

| System | Markdown: top 1 / 10, MRR | Plain: top 1 / 10, MRR | MRR change |
|---|---|---|---|
| e5-large | 0.60 / 0.92, 0.71 | 0.67 / 0.91, 0.75 | +0.04 (+0.00 to +0.09) |
| bge-large | 0.62 / 0.92, 0.74 | 0.69 / 0.93, 0.78 | +0.04 (+0.00 to +0.08) |
| MPNet | 0.23 / 0.59, 0.33 | 0.37 / 0.72, 0.48 | +0.15 (+0.10 to +0.20) |
| MiniLM | 0.33 / 0.74, 0.45 | 0.46 / 0.82, 0.57 | +0.12 (+0.07 to +0.17) |
| BM25 | 0.44 / 0.78, 0.54 | 0.43 / 0.78, 0.53 | −0.01 (−0.04 to +0.02) |
| e5-large + BM25 | 0.60 / 0.90, 0.70 | 0.57 / 0.92, 0.69 | −0.01 (−0.04 to +0.03) |
| bge-large + BM25 | 0.62 / 0.91, 0.72 | 0.61 / 0.93, 0.71 | −0.01 (−0.05 to +0.02) |

**Literal against paraphrased questions** (MRR, plain chunks):

| System | Literal (92) | Paraphrase (86) |
|---|---|---|
| e5-large | 0.82 | 0.68 |
| bge-large | 0.81 | 0.74 |
| BM25 | 0.75 | 0.30 |
| e5-large + BM25 | 0.84 | 0.53 |
| bge-large + BM25 | **0.88** | 0.52 |

**MRR by category** (Markdown → plain):

| Category (questions) | e5-large | bge-large | BM25 | bge-large + BM25 |
|---|---|---|---|---|
| Lookup (44) | 0.85 → 0.87 | 0.88 → 0.94 | 0.57 → 0.55 | 0.82 → 0.80 |
| Behaviour (26) | 0.36 → 0.41 | 0.52 → 0.56 | 0.47 → 0.48 | 0.54 → 0.61 |
| Near-duplicate (22) | 0.69 → 0.79 | 0.77 → 0.81 | 0.44 → 0.40 | 0.57 → 0.53 |
| Instance (20) | 0.86 → 0.88 | 0.77 → 0.81 | 0.65 → 0.46 | 0.83 → 0.79 |
| Tagged value (16) | 0.65 → 0.81 | 0.72 → 0.76 | 0.38 → 0.40 | 0.57 → 0.53 |
| Requirement by id (14) | 0.39 → 0.36 | 0.45 → 0.31 | 0.61 → 0.70 | 0.79 → 0.75 |
| Multi-hop (6) | 0.71 → 0.83 | 0.81 → 0.89 | 0.47 → 0.61 | 0.67 → 0.76 |

**What this says:**
- **Plain chunks again do as well or better** with every dense model, as on the judged real
  samples (`chunk-styles-2026-10-01.md`). The smaller models gain most.
- **Keyword search helps literal questions and hurts paraphrases when fused at equal weight.**
  Fused with BM25, bge-large leads on literal questions (0.88), but falls from 0.74 to 0.52 on
  paraphrases, because BM25 alone finds few of them (0.30). A stack that adds keyword search
  should weight it below the vectors, or use it for queries that look like ids and names.
- **Behaviour is the hardest to find.** Facts in activities and state machines sit in long lists
  of nodes, edges and transitions, which embed poorly (MRR 0.41 and 0.56 for e5-large and
  bge-large). Rendering a behaviour
  as readable steps ("after X, Y; if [guard], Z") is worth trying.
- **Ids remain a keyword problem.** For a requirement by its id, the embeddings' MRR is about a
  third (0.31 to 0.36).
  The traffic project's ids differ by a digit or two (PCT-SYS-0302, PCT-SYS-0304), which is
  hard for BM25 too.
- **The difficulty guessed in advance doesn't predict retrieval.** The questions tagged
  "medium" (behaviour, requirement ids) were harder for the dense models than those tagged
  "hard" (near-duplicates and instances, which name their subject exactly). The categories
  are the better guide.

## Limits

- **One author.** The same author wrote the models and the questions, so the questions may fit
  the models' wording better than real users' would. The paraphrases are the better guide.
- **Older distractors.** The real samples in the index are the earlier builds (0.5.0 plain,
  0.4.3 Markdown), without today's fixes. Only the fiction was built with 0.5.1.
- **Small subsets.** Some categories have few questions (multi-hop 6, notes 2).

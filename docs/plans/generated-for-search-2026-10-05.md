# Plan: generated text that serves search, 2026-10-05

- **Status:** In progress, started on 2026-10-05.
- **Step prefix:** `GS`, so steps are `GS-01`, `GS-02` and so on.
- **Addresses:** the maintainer, 2026-10-05, after ADR-0028 left the LLM's summaries and diagram
  descriptions out of `rag/`:
  > "If the purpose is to support 'aboutness' and paraphrased searches, perhaps we shouldn't
  > waste our budget on proper nouns or exact values; e.g. explicitly ask for inferred purpose or
  > intentions to support paraphrased lookups, avoiding proper nouns and exact values, enabling
  > the model to... perhaps not directly decline, but to generally classify the message against a
  > template so we can separately choose to decline certain classifications from entering RAG.
  > Providing more context is another lever to test."

## Why

The summaries crowd out answers (`docs/research/ledgers-and-generated-2026-10-05.md`):
- **What we ask for:** a package's "purpose, main elements, and how they relate", with the names
  as written; a diagram's purpose, from its legend and connections.
- **What we give:** 73% of package-summary inputs on the samples (85% of part summaries') hold no
  documentation at all; a diagram request holds names and arrows only.
- **What comes back:** inventories of names, and diagrams' connections retold. They match what a
  question names, and hold none of its facts.

Search by meaning needs what the names don't say: what a package or diagram is for, in the words
a person would use.

## Design

**Two levers, measured apart:**
- **The request** (`current` or `about`):
  - `current`: the templates in use (package-summary v4, module-summary v3, package-synthesis
    v3, diagram-description v6).
  - `about`: say what the package or diagram is about and what it is for, in everyday words and
    the domain's common terms. Infer purpose where the text implies it, and say nothing it
    doesn't support. No element names, identifiers or exact values: the chunk's heading names
    the package or diagram, and the extracted chunks hold the rest. At most 80 words.
- **The context** (`plain` or `context`):
  - `plain`: as now.
  - `context`: for a package, what the model and the package's owner say of themselves (their
    documentation, cut). For a diagram, each shown element's documentation (its first sentence),
    a state's entry, do and exit behaviors, and the documentation of the diagram's context
    element.

**A class first:** an `about` answer starts with a line `Class: <class>`, from a fixed list.
- **Packages:**
  - `intent`: it states purposes, rationale or how things are meant to work;
  - `structure`: parts, types and relationships, with little stated purpose;
  - `register`: many like items told apart by names and values (sites, instruments, test runs);
  - `requirements`, `behavior`, `library` (types, units, stereotypes for reuse), `results`
    (recorded values of an analysis or configuration);
  - `sparse`: too little to say anything.
- **Diagrams:** `flow`, `states`, `structure`, `interfaces`, `requirements`, `overview`, `sparse`.
- **The class goes in the chunk's metadata** (`about_class`) and in `rag/meta`. Which classes
  enter `rag/` is decided by measurement, not asked of the model.

**Four variants:** `current/plain` (the 0.19.0 answers, cached), `current/context`, `about/plain`
and `about/context`.

**Developer-only:** a script builds a tree with a variant's templates and context (they are part
of each project's options, so the projects it touches are written again). No user setting
(ADR-0027).

**What is measured:**
- **Against the default:** each variant's chunks in `rag/` (`assemble_tree.py --rag-all`),
  compared with `rag/` as it is now, without them (ADR-0028).
- **By class:** each variant's chunks with some classes left out.
- **Questions:**
  - the 234 of plan RM (the 226 standing questions and the 8 list questions);
  - new questions about where something is described ("Which part of the kiosk model covers how
    returned items are sorted?"), each literal and as a paraphrase, graded by element: a window of
    the package, diagram or behavior that answers.

## Steps

| Step | What | Status |
|---|---|---|
| GS-01 | **The `about` templates** for package summaries, part summaries, syntheses and diagram descriptions, with the class line; not in use by default. The class is parsed from the answer and carried to the chunk's metadata and `rag/meta`; an answer without a valid class line is kept, with the class `unknown`. Tests with a fake model. | |
| GS-02 | **Context slots,** filled by `prompt_values` for every request, used only by the `context` templates (packages: the model's and the owner's documentation, cut; diagrams: shown elements' first sentences, states' behaviors, the context element's documentation). Tests. | |
| GS-03 | **The variant builder,** `scripts/build_variant.py`: a tree built with a variant's templates. Measured on a copy of a store. | |
| GS-04 | **Questions about where something is described,** in the fiction: six, each literal and as a paraphrase, graded by element. A test that each answer's element exists and has a chunk. | |
| GS-05 | **Screening on the fiction:** a tree of the fiction alone for each variant (about 150 requests each); retrieval with each variant's chunks in `rag/` against without, on the 234 questions and GS-04's, and by class. | |
| GS-06 | **A reading on real models:** each variant on two sample projects (the drone and a SAF model): 20 package answers and 20 diagram answers each, read for faithfulness and for what they add; the classes' spread. | |
| GS-07 | **The decision and a release check:** the variant and the classes that enter `rag/`; the whole tree built with them (about 5,700 requests), compared with the default; an ADR, the docs, a version. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: requests | GS-01 to GS-03 | Variant requests, classes in the metadata, a builder |
| CP2: screening | GS-04, GS-05 | Which variants, and classes, stop crowding and help where-is questions |
| CP3: reading | GS-06 | Whether the answers are faithful and worth reading, on real models |
| CP4: decision | GS-07 | A default, or none |

## When to stop and ask

- **After CP2,** if no variant's chunks in `rag/` are at least as good as none, on every question
  set: the plan stops with the numbers.
- **After CP3,** with the numbers and the readings: the maintainer chooses (a change to what
  `rag/` holds, and to what the pages show).
- **Faithfulness:** if the `about` answers invent purposes the text doesn't support, in the
  reading, the plan stops.

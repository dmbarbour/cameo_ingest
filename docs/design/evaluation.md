# Design: evaluating retrieval

How retrieval over the output is measured, and how a change is shown not to hurt it. Decisions:
ADR-0022, ADR-0023. Plan RE (`docs/archive/plans/retrieval-evaluation-2026-09-30.md`) holds the
full history.

## What is simulated

The maintainer's RAG stack isn't ours to control. It cuts text into 512-token windows with some
overlap and retrieves densely, with no reranker assumed. The evaluation cuts windows of 512 tokens
with 64 of overlap on e5-large's tokenizer (`windows.py`, counting 2 special tokens), over:
- `chunks.jsonl`;
- `rag/` as the stack reads it (`--rag`);
- the tree's Markdown pages, as a stack pointed at the tree would read them (`--pages`; with
  `--rag` too, the whole tree's text; plan RM-05). Each file is cut across its sections, and a
  window is credited to the element whose section it starts in: a section starts at an anchor,
  and its trace line names the element. A project's README, ledger, threads and hierarchies are
  its model's, and `CROSSREF.md` counts as `index:id`, as its chunks do.

Kinds can be left out by glob (`--without ledger:* generated:*`, plan RM-01), with no rebuild:
the embeddings are cached by text, so a variant costs only the reranking of new candidates.

Every model runs on DeepInfra (embeddings, rerankers, judges); local runs are out on this machine.
A model DeepInfra doesn't serve gets a stand-in, reported as such: `BAAI/bge-large-en-v1.5` for
`llmrails/ember-v1`, the same shape. Embeddings are cached in SQLite by model, endpoint, role and
the sha256 of the text as sent. Search is exact cosine in numpy.

## Questions, and how each is graded

| Set | Questions | Graded by |
|---|---|---|
| Fictional projects (`scripts/make_fictional_projects.py`) | 262 now (`out/eval/fiction/questions.jsonl`); 210 without KOIS (`questions-ra.jsonl`, used for every comparison since plan RA); 8 about Port Calder's type hierarchy (`questions-th.jsonl`, plan TH); 8 that start from a diagram (`questions-is.jsonl`, plan IS); 8 that ask for a list, what ledgers are for (`questions-rm.jsonl`, plan RM) | Construction: rules `source`, `parts`, `fact` (only a window holding the fact gets a 2), `element` |
| Structural (`scripts/write_questions.py`) | 88 about the samples: by id, relationship, diagram, parameter | Construction; lexical-friendly, so for regressions, not model choice |
| Natural | Two sets of 75, written by DeepSeek-V3.2 from Markdown and from plain chunks | The judges |

- **The fictional projects** are seven invented Cameo projects, ours to share
  (`evaluation.fiction.PROJECTS`), in the format Cameo writes:
  - Kestrel Orchard Irrigation;
  - Ashgrove Library Book Return Kiosk;
  - Riverbend Water Treatment Works, in three proposals;
  - Ferrous Valley Level Crossing;
  - Port Calder Traffic Signal System.

  Their questions are tagged by category, difficulty, and literal or paraphrase. A test checks
  that each answer is where its key says. They are indexed beside the samples, as distractors.
- **Scores before 2026-10-02 aren't comparable** with later ones: KOIS was rebuilt with the fact
  rule (RA-17).

## Judges

- **The pool:** the top 10 of every system; each pair is judged once and cached
  (`scripts/judge_pools.py`). Passages go as plain text, cut at 4,000 characters.
- **The judges:** DeepSeek-V3.2 and Qwen3-235B; when they disagree, the lower grade wins. Pass
  `--tiebreak none` to `retrieval_eval.py` for that rule, since its default is Kimi-K2.
- **Agreement:**
  - the two judges agree at kappa 0.43 to 0.51;
  - against Claude's labels on 200 pairs: DeepSeek 0.27, Qwen 0.04, the lower-grade rule 0.35, and
    Kimi 0.61 (on 70 pairs).

  The panel is generous with 2s (Claude agreed with 13 of 28), so absolute scores are optimistic,
  while paired comparisons hold.
- **Checks:** `judge_pools.py` also reports how many known answers are graded 2, and how many
  passages from another project are credited.

## Systems and measures

- **Systems:**
  - BM25 (k1 1.2, b 0.75, keeping ids whole);
  - dense retrieval with each model (e5-large with and without prefixes, bge-large, mpnet,
    minilm);
  - reciprocal rank fusion (k 60, depth 100, `--bm25-weights`);
  - each reranked over its top 30 (`--rerank qwen3-0.6b|4b|8b`).
- **Measures, per question:** hit@1, 5, 10 and 20; MRR@10; nDCG@10; and, for answers in several
  parts, coverage@10 and complete@10.
- **The report:** `report.md` gives each system's 95% bootstrap interval (2,000 rounds) for hit@10
  and MRR@10.
- **Outputs:** `rankings.jsonl`, `per_question.jsonl`, and `run.json`, which records the tree,
  units and windows, so the judges grade identical windows.

## Comparing two trees

- **Pairing:** the same questions on both trees, paired by question id.
- **Significance:** a paired bootstrap of 4,000 rounds, 95% (`harness.paired_ci`). A change is
  significant when the interval of the mean difference excludes zero. `report.compare` pairs two
  runs' `per_question.jsonl` by system and question; questions asked in one run only are counted
  and left out. It also names the questions that only one run found in its top 10.
- **Noise:** with 75 to 88 questions, MRR differences under about 0.07 are noise; 210 questions
  narrow that.
- **The commands for a release check:** retrieval on the new tree, then the comparison with the
  reference run, which exits 1 when a measure changed significantly.

  ```
  uv run --extra eval python scripts/retrieval_eval.py TREE --env .env --models e5-large-bare \
      --questions out/eval/fiction/questions-ra.jsonl --rag --rerank qwen3-0.6b --out DIR
  uv run --extra eval python scripts/compare_retrieval.py REF_DIR DIR --out DIR/comparison.md
  ```

## Findings that shaped the output

| Finding | Source |
|---|---|
| Plain chunks never worse than Markdown, better for ids and small models, half the tokens | `docs/research/chunk-styles-2026-10-01.md` |
| One window per `rag/` file: MRR within ±0.02 | plan RE-11 |
| Reranking first: any hybrid reranked reaches MRR 0.82; the 0.6B reranker ties the 8B. Without a reranker, BM25 at weight 0.25 | `docs/research/rerankers-2026-10-01.md` |
| The identifier index raises coverage@10 from 0.77 to 0.97; threads cost nothing measurable; line references cost completeness | `docs/research/related-facts-2026-10-01.md` |
| Embeddings rarely find a requirement by its id; keyword search does | `docs/research/retrieval-baseline-2026-10-01.md` |
| Plan SK's descriptions and sketches: no significant change (the questions ask for facts the deterministic text carries) | `docs/research/sketch-ambiguities-2026-10-03.md` |
| 0.15.2's tables' rows, resolved self-references and plain legends: no significant change | `docs/research/used-objects-2026-10-03.md` |
| Generated chunks crowd out answers to fact questions (reranked MRR@10 +0.026 to +0.038 without them); ledgers answer lists | `docs/research/ledgers-and-generated-2026-10-05.md` |
| The pages alone, in place of `rag/`, lose a lot (e5-large's MRR@10 0.74 → 0.56); beside it, they fill the top 10 with duplicates | `docs/research/windows-over-pages-2026-10-05.md` |

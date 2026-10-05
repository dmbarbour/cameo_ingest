# Research: the pages, or the whole tree, in place of `rag/`? 2026-10-05

**Question.** Plan RM (`docs/archive/plans/retrieval-measures-2026-10-05.md`, RE-05 of plan RE). The
README says to point a RAG tool that reads files at `rag/text/` alone. What does it cost if the
stack is pointed at the Markdown pages instead, or at the whole tree?

**Method.**
- **The tree:** `out/v019/on`, the samples and the fiction at 0.19.0 with the LLM.
- **Three corpora, as a stack would read them:**
  - **`rag/`:** its 83,804 files, one window each (the reference);
  - **the pages:** every Markdown file in the tree (104 MB), each cut into windows of 512 tokens
    with 64 of overlap, across its sections: 95,351 windows (`retrieval_eval.py --pages`, plan
    RM-05);
  - **the whole tree's text:** both, 179,155 windows (`--pages --rag`). A stack that reads
    `.json` files would also take `rag/meta/`'s 83,804 metadata files; they weren't included.
- **Grading:** a page's window is credited to the element whose section it starts in (the
  section's trace line names it); a project's README and ledger are its model's; `CROSSREF.md`
  counts as `index:id`, as its chunks do.
- **The systems and questions:** as in `docs/research/ledgers-and-generated-2026-10-05.md`, on
  the 234 questions (the 226 standing ones and the 8 list questions).
- **A first run was flawed** (`out/rm/units-pages-recut`). The harness cut each page's windows a
  second time, and about 11,700 of them split, since a window re-tokenized alone can gain a
  token. Cut once, as here, the pages did about 0.03 better on MRR@10, with the same conclusion.

## Results

**The pages alone,** against `rag/`; \* significant.

| System | MRR@10 | nDCG@10 | hit@10 | coverage@10 |
|---|---|---|---|---|
| BM25 | 0.538 → 0.507 | 0.458 → 0.417\* | 0.791 → 0.774 | 0.768 → 0.750 |
| e5-large | 0.740 → 0.560\* | 0.616 → 0.450\* | 0.910 → 0.821\* | 0.899 → 0.791\* |
| e5-large + BM25 | 0.708 → 0.588\* | 0.588 → 0.468\* | 0.923 → 0.842\* | 0.911 → 0.805\* |
| BM25, reranked | 0.725 → 0.635\* | 0.591 → 0.510\* | 0.850 → 0.838 | 0.837 → 0.815 |
| e5-large, reranked | 0.758 → 0.664\* | 0.644 → 0.538\* | 0.944 → 0.876\* | 0.936 → 0.844\* |
| e5-large + BM25, reranked | 0.760 → 0.668\* | 0.643 → 0.543\* | 0.936 → 0.868\* | 0.928 → 0.843\* |

**Why:** the pages are written for people.
- **Nearly half their text is apparatus:** link targets 31.6%, front matter 6.8%, trace lines
  5.8%, anchors 3.5%.
- **A window cut from the middle of a section** doesn't say whose it is. `rag/`'s chunks repeat
  their heading in every part.

**The whole tree's text** (the pages and `rag/text/`), against `rag/`; \* significant.

| System | MRR@10 | nDCG@10 | hit@10 | coverage@10 |
|---|---|---|---|---|
| BM25 | 0.538 → 0.507\* | 0.458 → 0.401\* | 0.791 → 0.795 | 0.768 → 0.772 |
| e5-large | 0.740 → 0.701\* | 0.616 → 0.500\* | 0.910 → 0.889 | 0.899 → 0.871 |
| e5-large + BM25 | 0.708 → 0.665\* | 0.588 → 0.496\* | 0.923 → 0.876\* | 0.911 → 0.854\* |
| BM25, reranked | 0.725 → 0.735 | 0.591 → 0.525\* | 0.850 → 0.863 | 0.837 → 0.847 |
| e5-large, reranked | 0.758 → 0.752 | 0.644 → 0.554\* | 0.944 → 0.923 | 0.936 → 0.910 |
| e5-large + BM25, reranked | 0.760 → 0.759 | 0.643 → 0.569\* | 0.936 → 0.919 | 0.928 → 0.908 |

- **The first answer** is found about as well once reranked, since `rag/`'s windows are there.
- **The rest of the top 10** fills with the same facts again, from the pages: nDCG@10 falls for
  every system, by 0.06 to 0.12. An LLM given the top five would see fewer distinct facts.

## Decision

The README's advice stands, now with numbers: point a RAG tool that reads files at `rag/text/`
alone.

## Also found

- **The harness held a corpus three times over** while embedding it, and built BM25's postings as
  lists of Python ints; the whole tree's 179,155 windows exceeded the 3 GB memory cap. Rows are now
  filled into one matrix and normalized in place, and the postings are typed arrays: the same
  rankings, byte for byte (`out/rm/units-rag-check`), and the whole tree fits.

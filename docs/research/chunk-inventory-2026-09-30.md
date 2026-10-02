# Chunk inventory against the target embedding models

- **Date:** 2026-09-30
- **For:** plan step RE-01 in `docs/plans/retrieval-evaluation-2026-09-30.md`
- **Method:** `scripts/chunk_inventory.py out/all` (retired; at tag `studies-2026-10-02`), run under a 3 GB memory cap (peak 2.0 GB,
  3.6 minutes). It counts each chunk's length in each model's own tokens, with Hugging Face's
  tokenizers, and cuts the text into the windows the production stack is thought to make.
- **The corpus:** `out/all` (version 0.4.3), every sample except TMT-2024x: 19 projects and
  28,220 chunks, of which about 21,000 are TMT's.
- **The models:** those evaluated on DeepInfra (decision 8). `BAAI/bge-large-en-v1.5` stands in for
  ember-v1; both use BERT's uncased vocabulary, so their token counts agree closely.

## Lengths against each model's limit

| Kind | Chunks | e5-large (median) | Over 512 | bge-large (median) | Over 512 | MPNet (median) | Over 384 | MiniLM (median) | Over 256 |
|---|---|---|---|---|---|---|---|---|---|
| element | 14,923 | 299 | 19% | 297 | 18% | 297 | 26% | 297 | 58% |
| requirement | 4,382 | 484 | 41% | 459 | 35% | 459 | 75% | 459 | 98% |
| diagram | 2,241 | 764 | 73% | 747 | 73% | 747 | 89% | 747 | 98% |
| generated:diagram_description | 1,632 | 204 | 0% | 175 | 0% | 175 | 1% | 175 | 8% |
| generated:module_summary | 1,629 | 284 | 1% | 244 | 0% | 244 | 3% | 244 | 37% |
| ledger | 1,439 | 149 | 24% | 133 | 23% | 133 | 26% | 133 | 31% |
| package | 1,122 | 424 | 43% | 410 | 43% | 410 | 52% | 410 | 69% |
| generated:module_description | 461 | 304 | 3% | 266 | 2% | 266 | 11% | 266 | 53% |
| generated:summary | 339 | 293 | 0% | 250 | 0% | 250 | 1% | 250 | 47% |
| generated:image_description | 33 | 185 | 0% | 159 | 0% | 159 | 0% | 159 | 12% |
| project | 19 | 1,339 | 89% | 1,245 | 89% | 1,245 | 89% | 1,245 | 95% |

- **The extracted chunks run long:**
  - about a third of requirement chunks, and nearly three quarters of diagram chunks, exceed even
    512 tokens;
  - at MiniLM's 256 tokens, nearly all of them are cut.
- **The generated chunks fit:** under 512 tokens almost without exception, since their prompts ask
  for 120 to 200 words.
- **The e5 tokenizer** (multilingual, XLM-RoBERTa's) counts about 5% more tokens than BERT's on this
  text.

## What fills the chunks

Of all chunk characters, 27% are link targets (`](../packages/…#anchor-id)`), 11% qualified names and
7% trace lines. They serve readers and provenance, but in an embedding they take room from the
content. A DOORS requirement in TMT, for instance, spends about 100 tokens on its title, its kind
and a 20-level qualified name before its text begins.

## Windows, as the production stack is thought to cut them

Windows of 512 tokens with 64 tokens of overlap, cut on the model's own tokens:

| Model | From `chunks.jsonl` | From the Markdown pages |
|---|---|---|
| e5-large | 47,116 | 51,153 (from 3,405 pages) |
| bge-large | 46,354 | 50,697 |

With windows, a long chunk is split rather than cut, so nothing is lost outright. But a window that
starts in the middle of a section carries none of the section's heading, the element's name
included, unless the text repeats it. Embedding either set costs about 20 cents per model on
DeepInfra.

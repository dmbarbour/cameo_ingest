# How gemma-4 sees images

- **Date:** 2026-09-30
- **Origin:** written for the maintainer's `semantic_pdf_diff`, and copied here for FU-015. Its links to
  round 1 and the lever index point into that project.
- **Asked by:** the owner: "can you study gemma-4's image processing? I think it's a bit more sophisticated than a fixed budget, something about patches and spooling."
- **Method:**
  - Primary sources, read by a research agent: the [tech report](https://arxiv.org/html/2607.02770v1), the [model card](https://ai.google.dev/gemma/docs/core/model_card_4), the Hugging Face processor code ([image_processing_gemma4.py](https://github.com/huggingface/transformers/blob/main/src/transformers/models/gemma4/image_processing_gemma4.py), [modeling_gemma4.py](https://github.com/huggingface/transformers/blob/main/src/transformers/models/gemma4/modeling_gemma4.py)), the [vLLM recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html), [DeepInfra's vision docs](https://docs.deepinfra.com/chat/vision).
  - Probes of DeepInfra's `google/gemma-4-31B-it`: 16 requests with one short text and synthetic images, at `max_tokens` 1 (a fraction of a cent).
- **Earlier:** round 1's research already had the 645,000-pixel limit ([round-01 heuristics](round-01-context-heuristics-2026-09-26.md)), but renders stayed at 1,000 px on the long side.

## How it works

- **Patches:** a vision transformer cuts the image into 16 × 16-pixel patches; the 31B and 26B-A4B models use a ~550M-parameter encoder.
- **Pooling:** each 3 × 3 block of patches (48 × 48 px) is averaged into one "soft token".
- **Resizing:** the image keeps its aspect ratio, and is scaled up or down so its patches fill the budget. The scale is √(budget × 48² ÷ area), with each side rounded down to a multiple of 48. There's no padding, no cropping, and no pan-and-scan; tiling is left to the caller.
- **Budget:** 70, 140, 280, 560 or 1120 soft tokens per image; 280 by default. An image then costs its pooled tokens plus a begin and an end marker.

| Budget | Pixels seen (at most) | Largest square |
|---|---|---|
| 70 | ~161,000 | 384 px |
| 140 | ~323,000 | 528 px |
| **280 (default)** | ~645,000 | 768 px |
| 560 | ~1.3 million | 1104 px |
| 1120 | ~2.6 million | 1584 px |

- **Setting it:** transformers takes `max_soft_tokens` on the processor; vLLM takes `mm_processor_kwargs={"max_soft_tokens": ...}`, per server or per request.
- **Why it matters:** the tech report measures reading documents at 1120 against 280 (31B). InfographicVQA scores 92.0 against 82.8; OmniDocBench edit distance is 0.131 against 0.201 (lower is better). Google's guidance: "Use higher budgets for tasks like OCR, document parsing, or reading small text", and put images before the text.

## What DeepInfra does (measured)

- **Every image costs the default budget, whatever its size:** a square from 64 × 64 to 2000 × 2000 costs 258 tokens (256 pooled, plus 2). 4:1 (either way round) costs 266, 10:1 costs 262, and 2:1 costs 255. Exactly what transformers and vLLM predict at 280.
  - My earlier note ("a flat ~284 tokens") counted some prompt overhead with the image.
- **Neither setting changes it:** a 1000 × 1000 image costs 258 with `mm_processor_kwargs: {"max_soft_tokens": 1120}` and with `detail: "high"`. Both are silently ignored.
- **Images are cheap here:** 258 tokens cost about $0.00003. Output tokens dominate a query's cost.

## What this means for us

- **Tiles:** 420-point tiles rendered at 1000 × 1000 are shrunk to 768 × 768 before the model sees them. That's about 1.8 px per point, one token per ~26 points of drawing. Rendering above 768 px gains nothing.
- **Bands are hurt most:** a 4:1 report band rendered at 1000 × 250 is *enlarged* to 1584 × 384. Only ~250,000 real pixels reach the model, against ~590,000 for a tile. Rendering bands at the budget's size (1584 × 396) would give ~1.6 × the linear detail for the same tokens.
- **Overviews are coarse:** a whole 24 × 36-inch sheet gets ~0.4 px per point, and small dimension text is a few pixels tall, under one patch. This fits labels misread on drawings (2'-9 1/2" read as 2'-3").
- **Levers these suggest** (added to the [lever index](../reviews/levers.md) as ideas):
  - **Render every region at the budget's size:** about 645,000 px, sides in multiples of 48. Free, and it helps bands most.
  - **Smaller tiles on drawings:** 280-point tiles give 1.5 × the linear detail at 2.25 × the tiles. The extra image tokens cost little, though more queries also produce more output.
  - **Images before text** in each query, as Google advises.
  - **A higher budget** (560 or 1120) needs a host that sets `max_soft_tokens`, such as the in-house deployment if it runs vLLM. Renders would then need to be larger too (1104 or 1584 px).

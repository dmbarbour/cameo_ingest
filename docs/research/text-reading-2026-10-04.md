# Research: how evenly text models read long inputs, 2026-10-04

**Question.** A large package is summarized in parts of at most 12,000 characters
(`PART_CHARS`), a constant measured for gemma-4 at that one size. How long an input do text
models read evenly, from start to end? Could calibration set the part size for whichever model
is configured, as it sets the sketches for the vision model? This is plan TC-03 and TC-04
(`docs/archive/plans/text-calibration-2026-10-04.md`).

**Method.**
- **Reading cards** (`textcal.py`): synthetic package text in the plain form of real parts,
  every name and figure invented. Lengths of 6,000 to 192,000 characters, 8 cards per length,
  from fixed seeds.
- **Two probes on each card:**
  - **summary:** the real part request (`module-summary@v3`, at most 120 words), scored by
    position in the input;
  - **facts:** five questions, each about a figure in a different fifth of the input.
- **Models:** gemma-4-31B-it and DeepSeek-V3.2, both on DeepInfra: 96 requests each on the final
  cards.
- **Script:** `scripts/measure_text_reading.py`. Results are in `out/tc/`.

## First cards: alike elements (discarded)

The first cards held about 2 elements per 500 characters, all alike: blocks with a figure, and
requirements on them. Scored by elements named:
- **gemma-4** named almost all of a 6,000-character card's elements, about 40% of a
  12,000-character card's (72% in the first fifth, 28% to 39% in the middle), and at 48,000 and
  more only elements from the first fifth.
- **Facts** were found at every length and position.

**Its summaries were right.** A card of alike elements is summed up by its pattern, with a few
examples, and the model took its examples from the start. The probe measured how examples are
chosen, not what was read.

## Second cards: five groups

Each fifth of a card now holds a group:
- a hub block with a purpose of its own ("desalinates seawater for the habitat");
- blocks "for" the hub, and requirements on them.

A summary covers a group when it names the group's hub, or the keyword of its purpose
("seawater").

**Groups covered by each fifth's position, and facts right,** over 8 cards a length:

| Characters | gemma-4: groups | gemma-4: facts | gemma-4: elements named | DeepSeek: groups | DeepSeek: facts | DeepSeek: elements named |
|---|---|---|---|---|---|---|
| 6,000 | 100% | 100% | 100% | 100% | 100% | 62% |
| 12,000 | 100% | 100% | 94% | 100% | 100% | 25% |
| 24,000 | 100% | 100% | 27% | 100% | 100% | 7% |
| 48,000 | 100% | 100% | 15% | 100% | 100% | 4% |
| 96,000 | 90% (4th fifth 50%) | 97% | 2% | 100% | 97% | 2% |
| 192,000 | 97% (4th fifth 88%) | 97% | 1% | 100% | 97% | 1% |

- **Neither model loses its place in these cards** up to 192,000 characters (about 48,000
  tokens), 16 times today's part. gemma-4's dip at 96,000 doesn't recur at 192,000: with 8 cards,
  one miss is 12 points.
- **The two probes agree.** Facts are found almost everywhere at every length.
- **The models write differently.** At 12,000 characters, gemma-4's summaries list the elements
  (94% named); DeepSeek's characterize them (25%). Both stay near 120 words at every length.

## What this means for parts

- **The cards are easier than real packages.** In the sandwiching study, gemma-4 summarized real
  packages of over 100,000 characters in one request, and drew 13% of the names it mentioned from
  the middle third, against 21% in parts (`docs/research/sandwiching-2026-09-30.md`).
  - These cards state each group's purpose, and every member names its hub.
  - Real packages are long lists whose important elements nothing marks, and the failure is in
    choosing what matters.

  So the cards can't show where a strong model's reading of real packages sags. They do show
  that it doesn't sag for want of reading: both models find what they are asked for, anywhere.
- **The part size is also a choice about the summaries.**
  - At 12,000 characters, gemma-4's part summaries name almost every element; at 48,000, one in
    seven.
  - Larger parts would mean fewer requests (a fourth as many at 48,000) and fewer levels of
    synthesis, but coarser summaries.
  - The element names are in the deterministic chunks either way.
- **What calibration could still catch:**
  - a model that reads worse than these two;
  - a small context window, or an endpoint that cuts long inputs without saying so. Facts missed
    in the last fifths would show it.

  Both are failures at short lengths, cheap to measure.

## Cost

252 requests in all, with the first cards and a smoke test. None failed.

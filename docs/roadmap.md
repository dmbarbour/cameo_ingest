# Roadmap: open, deferred and tentative work

Gathered on 2026-10-03 from the retired plans and reviews (`docs/archive/`), whose IDs are given
so that their history can be found. When an item becomes a plan, it moves to `docs/plans/`.

## Waiting on the maintainer

- **The exports' trial** (KX-08, KX-09):
  - try the workbook and the search page on the fiction, then the samples, and share them through
    SharePoint;
  - choose between them, and whether the page carries sketches (WebP or SVG);
  - check the Find sheet's formula in Excel itself, and the policy on scripts in downloaded HTML;
  - check how SharePoint search treats hyphenated ids, and whether previews honour `#anchor`.
- **Exports by group** (KX-11, proposed): `export --group-by meta:KEY|folder`, one page and workbook
  per group, with an index of identifiers across them. Waits until the maintainer's corpus is
  counted (estimated at about 345,000 items: past the page's comfortable 300,000).
- **Retrieval spot check** (RE-04): the maintainer's check of generated questions,
  `out/eval/questions/spot-check.md`.
- **Questions for the RAG stack's owners** (RE-09):
  - which model, at what input limit;
  - how much overlap, and whether the splitter respects paragraphs;
  - whether a file name is shown as the source;
  - whether e5's prefixes are added;
  - how many chunks go into a prompt.

## Tentative plans

- **Recompute tables and matrices.** The file holds a table's configuration (scope, row types,
  columns), which is read (BASE-001), and its rows when last saved (`usedObjects`), which its page
  lists (`docs/research/used-objects-2026-10-03.md`). Only the cells are computed, from the rows'
  own properties. Rebuild the common cases: requirement tables, then allocation and dependency
  matrices, which store no rows.
- **Attachments:**
  - link `BINARY-*` images and documents to the elements that own them;
  - convert PDF and Office attachments to text;
  - then describe an image with what owns it: its name, kind and documentation (ADR-0017). Today
    the request says "nothing says which element owns it or where it appears".

  `pipeline` still writes image bytes itself (AR-007's residue).
- **Type hierarchies for search** (the maintainer, 2026-10-03):
  - a chunk per hierarchy, every kind at every level, as threads are for requirements;
  - large hierarchies cut by subtree;
  - later, the kinds that specialize a shared library type across models.

  TMT has 24 hierarchies, up to 4 deep; NIST_M-SysML one of 1,861 kinds, 9 deep. No sample has a
  generalization set.
- **Better module boundaries** (DV):
  - sequence diagrams in bands along the time axis;
  - activity diagrams along their partitions (swimlanes, from `inPartition`; TMT's aren't nested in
    the layout).

  Sequence diagrams also confuse validation and descriptions: messages join activations, while
  models name lifelines. Their lifelines, lines and activations repeat one name.
- **Calibrating the text model's reading, and cutting its inputs ourselves** (the maintainer,
  2026-10-04).
  - **Today:** a large package is summarized in parts of 3,000 to 12,000 characters
    (`PART_CHARS`, `SUMMARY_CHARS`). These are constants, measured for gemma-4
    (`docs/research/sandwiching-2026-09-30.md`):
    - at 12,000 characters (about 3,000 tokens) it reads an input's start, middle and end evenly
      (87%, 86% and 86% of names mentioned);
    - in one request of over 100,000 characters it loses the middle (13% from the middle third,
      against 21% in parts).

    Where in between its reading starts to sag wasn't measured, and another text model may do
    better or worse.
  - **Calibrate,** as the vision model is (ADR-0015):
    - synthetic inputs of rising length, with invented facts planted at known places, as in the
      fictional projects;
    - the model reports what it finds, and each length is scored by where the facts sat;
    - the longest input still read evenly sets the part size, recorded per text model and
      endpoint, beside the vision calibration.
  - **Cut inputs ourselves, never truncate:** a single section larger than a part is cut today at
    12,000 characters, and the rest is lost. In the 0.15.2 release check, 10 package parts were
    cut, from sections of 12,004 to 24,449 characters. Such a section should be split into pieces
    that each repeat its heading, as `rag/` files are, and summarized like any other part.
  - **Other cut points** could follow the same measure: `DIAGRAM_ITEMS` (150 shapes and
    connections listed per request) and `DIGEST_CHARS`.
  - **Not affected:** the RAG files are already cut to fit a 512-token embedding window (since
    0.5.0); what remains there depends on the RAG stack's model and chunker (RE-09).
- **Keyword search from the command line,** for when Python can run where the corpus is read.

## Sketches and the vision model

- **More cases where knowing Cameo helps a model read an image** (the maintainer's invitation,
  ADR-0017). Only embedded images (above) and module sketches have been examined.
- **Lines between undrawn ends:** some connections end at views that aren't drawn as shapes (TMT's
  collaborator views), and invite invented connections.
- **A margin for the arrows' rule:** 10 px heads pass at exactly 95% for both models measured;
  14 px read all 44.
- **The upward-arrow bias:** gemma-4 reverses 24 to 28% of upward arrows. Would a filled head or a
  mid-line arrow help? A spot check of descriptions with many upward arrows would tell whether it
  matters.
- **Direction in large modules:** Qwen3-VL reads 56% of directions right among 36 shapes, its
  calibrated module size. Should modules yield to direction?
- **A judged check of descriptions themselves,** beyond what validation measures from the image.

## LLM quality

- **The judge panel** (LQ-04 to LQ-06, deferred "until the obvious deficiencies are fixed and
  quality is less certain"). Proposed judges:
  - for images, `anthropic/claude-sonnet-5` and `google/gemini-3.1-pro`;
  - for summaries, `deepseek-ai/DeepSeek-V3.2` and `openai/gpt-oss-120b`.
- **Ratings at scale** (LQ-07): no panel or maintainer ratings yet; document `quality sample` and
  its rubrics for raters (LQ-08).
- **Residual:** gemma calls «DeriveReqt» links "refinements", though it reads their direction
  right.

## Retrieval evaluation

- **Windows over the pages** (RE-05), and generated and ledger chunks in or out (RE-08): untested.
- **A stricter judge prompt** (v2), and the Kimi tie-breaker on the plain pools
  (`out/eval/judge-plain2/run.sh`).
- **TMT-2024x as a test of confusion between versions.**

## Related facts

- **Facet lists** (RF-05, deferred): TMT's tags run to hundreds of requirements per value, and
  choosing the tags needs heuristics with only one example. Deferred with them: DOORS-like
  structure for the traffic project (RF-04).
- **Not built:** trace cards; threads from the DOORS hierarchy; graph bundles.

## Known gaps and small fixes

- **HTML in shapes' text:** a note's or text shape's text in the layout can be HTML (`<html>
  <head> <style> p {padding:0px…`), and legends show it as written: 72 of 6,551 stored diagram and
  module prompts, and 41 diagram pages, at 0.15.2. Documentation and tagged values are converted
  (`richtext`); shapes' text isn't. Converting it changes those requests.
- **Stale proxies:** a stale snapshot could name an element differently from Cameo. Nothing
  checks for this.
- **`quality`** still cuts an answer out of the rendered page with a regex (AR-012R2, partial by
  decision).
- **What a drawn diagram shows inside shapes:** its `usedObjects` also name compartment
  properties, operations, ports and triggers (12,095 elements in 594 diagrams of the samples).
  Its "Elements shown" and the elements' "Shown in diagrams" count only what is drawn.
- **The scripts are untested** (AR-022, accepted).

## Deferred indefinitely

- **`.mdzipx` SVGs** (the maintainer, 2026-10-02):
  - link each diagram's SVG to its diagram and use it in place of the sketch;
  - none of the maintainer's 282 Cameo files is an `.mdzipx`, and no public sample exists;
  - taken up again only if one turns up.
- **A zip bundle beside the search page** (KX's D8), unless the trial asks for it.
- **Rendering cost:** about 40 s for TMT's sketches; accepted, and `--no-render` skips it.

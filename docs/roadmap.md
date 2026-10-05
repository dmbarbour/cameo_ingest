# Roadmap: open, deferred and tentative work

Gathered on 2026-10-03 from the retired plans and reviews (`docs/archive/`), whose IDs are given
so that their history can be found; reviewed on 2026-10-05. Each item is described once, in its
section. When an item becomes a plan, it moves to `docs/plans/`. Done work leaves the roadmap:
its record is the archived plan, the ADRs and the design documents.

## Next, by ease and reward

Ranked on 2026-10-05, among the items that can progress now, without the maintainer or new
evidence. Everything ranked on 2026-10-04 is done: the quick wins (0.16.1), type hierarchies
(plan TH, 0.18.0), what shapes hold (plan IS, 0.19.0) and the review of the switches (ADR-0027).
Retrieval's untested measures are done too (plan RM, ADR-0028), and generated text that serves
search is a plan of its own (`docs/plans/`).

1. **Compartments in the legends, tested first** (Sketches and the vision model): cards whose
   legends list elements the image doesn't show, to learn whether telling the model what shapes
   hold helps or biases it.
2. **The text guard for other limits** (The text model): `DIAGRAM_ITEMS` and `DIGEST_CHARS`,
   guarded as the part size is. The calibration's machinery exists.
3. **Kinds of a shared library type across models** (Related facts): an index across models, as
   for identifiers.

Larger, or of less certain reward: better module boundaries (a reading of the descriptions
first), the judge panel, and TMT-2024x as a test of confusion between versions.

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
- **Keyword search from the command line:** worth building if Python can run where the corpus is
  read.
- **Retrieval spot check** (RE-04): the maintainer's check of generated questions,
  `out/eval/questions/spot-check.md`.
- **Questions for the RAG stack's owners** (RE-09):
  - which model, at what input limit;
  - how much overlap, and whether the splitter respects paragraphs;
  - whether a file name is shown as the source;
  - whether e5's prefixes are added;
  - how many chunks go into a prompt.

## Waiting on evidence

- **Computing more tables and matrices,** as a new plan if feedback asks for it (the maintainer,
  2026-10-04). Tables that list their rows are computed (plan CT, ADR-0025), and matrices are
  described in words (0.17.2).
  - **Tables that find their rows in a scope** (147 in the samples): a model that saved such a
    table's rows would test a rule. Whether opening and saving a table in Cameo stores them is
    untested.
  - **Matrices** (32 in the samples) store nothing they show. 11 of 32 have plain relationship
    criteria, scopes inside the model and no queries: they would be the easy ones. Nothing in the
    file shows what Cameo displays, though, so a computed matrix couldn't be checked, unless a
    matrix exported from Cameo can serve as truth.
- **Attachments:** the public samples hold 20 images and 1 PDF in all. Whether the maintainer's
  models have more decides this. If they do:
  - link `BINARY-*` images and documents to the elements that own them;
  - convert PDF and Office attachments to text;
  - then describe an image with what owns it: its name, kind and documentation (ADR-0017). Today
    the request says "nothing says which element owns it or where it appears".

  `pipeline` still writes image bytes itself (AR-007's residue).
- **Facet lists** (RF-05): TMT's tags run to hundreds of requirements per value, and choosing the
  tags needs heuristics with only one example. Deferred with them: DOORS-like structure for the
  traffic project (RF-04).

## Sketches and the vision model

- **Compartments in the legends** (plan IS's option C). Telling the vision model what each block's
  compartments hold "could improve feedback; on the other, it could overly bias the vision model"
  (the maintainer, 2026-10-05). Two ways to find out first:
  - **calibrate and test it,** with tricky cards: legends that list elements the image doesn't show,
    and descriptions scored for repeating them, as validation scores invented connections;
  - **progressive disclosure:** let the model ask for a shape's contents (a tool call) when it needs
    them, in place of putting them all in the legend. This needs an endpoint and model that support
    tool calls.
- **Better module boundaries** (DV). Each change costs a redraw and new descriptions, so a reading
  of descriptions where they apply would first show whether they matter.
  - Sequence diagrams in bands along the time axis. They also confuse validation and
    descriptions: messages join activations, while models name lifelines, and a lifeline, its
    line and its activations repeat one name.
  - Activity diagrams along their partitions (swimlanes, from `inPartition`; TMT's aren't nested
    in the layout).
- **Lines between undrawn ends:** some connections end at views that aren't drawn as shapes (TMT's
  collaborator views), and invite invented connections.
- **Messy layouts:** in TMT's "Duration Analysis" diagrams, a tree's bar runs along the edge of an
  unrelated shape, and models read the children as joined to it. No drawing rule fixes that layout
  (`docs/research/sketch-ambiguities-2026-10-03.md`).
- **More cases where knowing Cameo helps a model read an image** (the maintainer's invitation,
  ADR-0017). Only embedded images and module sketches have been examined.
- **A judged check of descriptions themselves,** beyond what validation measures from the image.
- **Arrows, deferred** (`docs/research/upward-arrows-2026-10-04.md`). Descriptions take each
  connection's direction from its text, and none of 175 upward connections checked was stated
  backwards. These matter again only if images are read without their connection lists:
  - a margin for the arrows' rule: 10 px heads pass at exactly 95% for both models measured, and
    14 px read all 44;
  - the upward-arrow bias: gemma-4 reverses 24% of upward arrows on the eye charts, which a filled
    head or a mid-line arrow might help;
  - direction in large modules: Qwen3-VL reads 56% of directions right among 36 shapes, its
    calibrated module size.

## The text model

After plan TC (the text model's calibration, a guard; ADR-0024):
- **The same guard for other limits:** `DIAGRAM_ITEMS` (150 shapes and connections per request)
  and `DIGEST_CHARS`.
- **Cards that lose real packages:** the reading cards are read evenly by strong models to
  192,000 characters, unlike real packages. Cards of long, unmarked lists, as real packages are,
  would be needed before letting any part grow (`docs/research/text-reading-2026-10-04.md`).

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

- **TMT-2024x as a test of confusion between versions.**
- **A stricter judge prompt** (v2), and the Kimi tie-breaker on the plain pools
  (`out/eval/judge-plain2/run.sh`).

## Related facts

- **Kinds of a shared library type across models** (after plan TH, ADR-0026): TMT's and
  TMT-2024x's analyses specialize one library's `MonteCarloAnalysis`, and SAF models specialize
  SysML's `Block`. Each model lists them; an index across models, as for identifiers, would bring
  them together.
- **Not built** (plan RF): trace cards; threads from the DOORS hierarchy; graph bundles.

## Known gaps and small fixes

- **Stale proxies:** a stale snapshot could name an element differently from Cameo. Nothing
  checks for this.
- **`quality`** still cuts an answer out of the rendered page with a regex (AR-012R2, partial by
  decision).
- **Most scripts are untested** (AR-022, accepted). `validate_sketches.py` and `assemble_tree.py`
  have tests.

## Deferred indefinitely

- **`.mdzipx` SVGs** (the maintainer, 2026-10-02):
  - link each diagram's SVG to its diagram and use it in place of the sketch;
  - none of the maintainer's 282 Cameo files is an `.mdzipx`, and no public sample exists;
  - taken up again only if one turns up.
- **A zip bundle beside the search page** (KX's D8), unless the trial asks for it.
- **Rendering cost:** about 40 s for TMT's sketches; accepted, and `--no-render` skips it.

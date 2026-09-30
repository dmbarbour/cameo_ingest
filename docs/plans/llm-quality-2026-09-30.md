# Plan: measuring LLM enrichment quality, 2026-09-30

- **Status:** Accepted on 2026-09-30, with the proposals in the open questions taken as
  answered (say if any should change). Template rating (goal 5) was added at the maintainer's
  request. In progress.
- **Step prefix:** `LQ`, so steps are `LQ-01`, `LQ-02` and so on
- **Addresses:** FU-006 in `docs/reviews/followup-2026-09-30.md`; it also measures the fixes
  for FU-001, FU-002, FU-004 and FU-005

## Goals

1. **Spot checks that anyone can do.** Make them easy, repeatable, and the same for the
   maintainer and for Claude: the same items, the same view of the input and response, and
   the same rubric.
2. **A judge panel.** Add a panel of independent model judges, from other model families
   than the generator, applying the same rubric to more items than people can.
3. **Knowing how far to trust the judges.** Compare the judges with the human ratings before
   relying on them.
4. **Attributing faults.** Tell a fault in the model's response from a fault in the input we
   sent it (spot check 1 found mostly the latter), and measure changes to extraction and
   prompts before and after on the same items.
5. **Rating the requests too (maintainer, 2026-09-30).** The quality of the question limits the
   quality of the answer, so the prompt templates are rated in their own right, not only
   through their responses. Each template is shown with obvious stand-ins in place of its
   image and text slots, and the stand-ins describe what will fill them. Spot check 1 showed
   the need: the diagram prompt tells the model its connection list is authoritative, which
   FU-001 and FU-002 make untrue.

## Items and rubric

An **item** is one LLM request and its response. It records:
- the kind (diagram description, image description, package summary);
- the exact prompt text and image sent;
- the response and the model;
- the project token and the element locator;
- **reference material** for checking: the diagram page (shapes and connections), or the
  whole package text, of which a summary may have seen only part.

The **rubric** for each item:

| Field | Values |
|---|---|
| `faithful` | yes / partly / no: every element, relationship and claim is supported by the input |
| `errors` | the unsupported or wrong statements (invented elements or groupings, wrong directions) |
| `omissions` | important content left out (main elements, flows, requirements) |
| `useful` | 1 to 5: would this text help someone find the item with a natural question? |
| `format` | ok / not ok: plain prose, within the length limit, no markup |
| `fault` | model / input / both / none: where a problem comes from |
| `notes` | free text |

### Template rubric

A template is the fixed text of a request, with named slots for what varies. Each is rated
with this rubric:

| Field | Values |
|---|---|
| `clear` | 1 to 5: is the task unambiguous? Would two careful people produce comparable answers? |
| `grounded` | yes / partly / no: does it confine the answer to the input, and say what to do when the input is not enough? |
| `context` | complete / gaps: does the input carry what the task needs? That includes notation explained, direction conventions, what the lists include and leave out, and whether anything was cut. |
| `accurate` | yes / no: are the template's own statements about its input true? |
| `output_spec` | ok / not ok: are the length, format, audience and required content stated? |
| `risks` | the errors the template invites: speculation, invented structure, markup, over-long answers |
| `suggestions` | concrete changes |
| `notes` | free text |

## Design

- **Template registry.** The prompts move into `prompts.py` as named, versioned templates
  (`diagram-description@v1`, `image-description@v1`, `package-summary@v1`). Each has its text,
  with `{{SLOT}}` markers, and a description of every slot: what fills it, its format, limits
  and truncation. Version 1 produces exactly today's requests, so stored answers and the
  replay fixture stay valid. Each request records its template key, and so does the LLM
  derivation of each response. A change to a template's text is a new version, which the
  report can compare with the old one.
- **Request log.** `llm.sqlite` gains a `requests` table, written with each answer. It holds
  the request hash, template key, item locator, project token, the text of each slot, the
  rendered prompt, and the sha256 and project path of any image. The store stays local, next to outputs that contain the same content.
  `scripts/record_llm_fixture.py` drops the table, so prompts built from third-party models
  never reach git.
- **Spot-check sets.** `cameo-ingest quality sample -o OUT [--n 30] [--seed S] [--kind ...]`
  draws a stratified random sample: across kinds and projects, with large and truncated
  inputs over-represented. It writes an immutable set to `OUT/quality/<set>/`:
  - `items.jsonl`: the items;
  - `templates.jsonl`: the templates the items used, with their stand-in renderings;
  - `index.html`: a self-contained page. It shows the templates first, each with its
    stand-ins, slot descriptions and rubric, then one section per item, with the image,
    prompt, reference material, response and rubric;
  - `rate-items.csv` and `rate-templates.csv`: empty rating sheets, one row per item or
    template, to be copied for each rater.

  Claude rates from the same material: it reads the images and text directly and fills in
  `ratings-claude.csv`.
- **Judge panel.** `cameo-ingest quality judge -o OUT --set <set> [--judges judges.toml]`.
  - **Configuration:** each judge is a name, an endpoint (base URL and key variable, by
    default the same `OPENAI_*` endpoint), a model, and whether it takes images.
  - **What each judge receives:** for an item, its input, reference material and response;
    for a template, its stand-in rendering and slot descriptions. The matching rubric comes as
    a JSON schema, and the judge answers in JSON.
  - **Checks:** the preflight check confirms each judge answers, and answers with images where
    required. Text-only judges rate only summaries.
  - **Storage and scale:** answers are stored like LLM answers (keyed by request hash), so a
    rerun is free, and requests run concurrently.
- **Ratings.** All ratings (people and judges) go into `OUT/quality/quality.sqlite`, one row
  per (item or template, rater), keeping the raw answer.
- **Report.** `cameo-ingest quality report -o OUT --set <set>` writes a Markdown or HTML page:
  - **Per kind:** the share rated faithful and the mean usefulness, for each rater.
  - **Agreement:** between each pair of raters, the share agreeing on `faithful` and the mean
    difference in `useful`, with judges set against the human ratings.
  - **Errors:** those flagged by two or more raters, grouped by `fault`.
  - **Templates:** each template's ratings and suggested changes, next to the item faults
    attributed to its input.
  - **Comparisons:** between two sets drawn from the same items, for before and after a
    change.

## Steps

The steps were renumbered on 2026-09-30, before any had started, to put the template registry
first.

| Step | Work | Status |
|---|---|---|
| LQ-01 | Template registry (`prompts.py`): named, versioned templates with described slots and stand-in renderings. Version 1 gives byte-identical requests. Requests and derivations record the template key. | Done: request hashes checked identical before and after |
| LQ-02 | Request log in `llm.sqlite`; the fixture recorder drops it; tests. | Done |
| LQ-03 | `quality sample`: stratified sampling, `items.jsonl`, `templates.jsonl`, the `index.html` spot-check page, rating sheets; tests with the fixture model. | Not started |
| LQ-04 | Ratings: import CSV ratings of items and templates into `quality.sqlite`, and validate them against the rubrics. | Not started |
| LQ-05 | `quality judge`: judge configuration, preflight, rubric prompts and JSON schemas for items and templates, storage, concurrency; tests with a fake client. | Not started |
| LQ-06 | `quality report`: per kind, per rater, agreement, errors by fault, template ratings, before and after. | Not started |
| LQ-07 | First round on public samples (the drone, a slice of TMT, SAF_FFDS for images): Claude rates, the panel judges, then the maintainer rates when convenient. Findings go into the follow-up review. | Not started |
| LQ-08 | Docs: README (quality commands, rubrics), and the review's status. | Not started |

## Open questions for the maintainer

Taken as answered on 2026-09-30: the maintainer found the plan good, so each proposal below
stands unless changed.


1. **Judges.** Your endpoint serves models from several families, so the panel needs no other
   provider. Proposed, subject to each passing the preflight check:
   - **for all items (they take images):** `anthropic/claude-sonnet-5` and
     `google/gemini-3.1-pro`;
   - **for summaries only (text):** `deepseek-ai/DeepSeek-V3.2` and `openai/gpt-oss-120b`.

   Would you prefer others, such as `anthropic/claude-opus-5-5` for accuracy at a higher cost,
   or `moonshotai/Kimi-K3`?
2. **Size of a round.** 30 items with 2 to 4 judges is roughly 100 judge requests, most with
   an image. Is that the right scale for a round?
3. **Where you rate.** Proposed: the local `index.html`, and a CSV you fill in, which works for
   private models too. The alternative is a claude.ai page with shared ratings, which is
   easier to use and which I can read directly, but it uploads model content, so it suits
   public samples only.
4. **Scope.** Should this also cover retrieval: a set of questions run against `chunks.jsonl`,
   checking whether the right chunks come back? That is listed below as a tentative separate
   plan.

# cameo-ingest

Convert Cameo Systems Modeler / MagicDraw projects into provenance-tagged Markdown, CSV and
JSON for RAG ingestion, without needing Cameo itself. It tolerates project files saved by
MagicDraw 18.x through Cameo 2026x, and it has been checked against 14 public sample projects
(see `samples/SOURCES.md`).

```sh
uv sync
uv run cameo-ingest MODEL.mdzip -o out/ (--no-llm | --env .env | --text-model MODEL) \
    [--meta program=XYZ] [--no-render] [-v]          # ingest one or more files or directories

uv run cameo-ingest add -o out/ more/models/ --meta supplier=ACME   # add to the task list
uv run cameo-ingest run -o out/                      # process it; continues a stopped run
uv run cameo-ingest status -o out/                   # what the tree holds
```

Supported inputs are recognized by their content, so the file extension doesn't matter:

| Input | Handling |
|---|---|
| `.mdzip` | ZIP. The model is read from `com.nomagic.magicdraw.uml_model.model`, plus any `…uml_model.shared_model` (library and profile projects keep their content there). Diagram layouts come from `BINARY-*` entries. |
| `.rdzip` and bundles | Resource-manager ZIPs of ZIPs. Every nested project is found, up to 4 levels deep, and each is a project of its own. |
| `.mdzipx` | Documented as an `.mdzip` plus one `.svg` per diagram. The nested `.mdzip` is ingested; the SVGs are not used yet (see Roadmap). No public sample exists to test against. |
| `.mdxml`, `.xmi` | A bare XMI document. |

## Working with an output tree

An output directory is a workspace that keeps its state in `state.sqlite`: a task list of
inputs, the Cameo projects found in them, where each was found, and what has been written.
Each project is identified by the sha256 of its own bytes, so it is processed once, however
many files, bundles or names it turns up under.

| Command | Does |
|---|---|
| `cameo-ingest add -o OUT PATH... [--meta K=V] [--meta-file F]` | Adds files to the task list. A directory adds the ZIP archives and XMI documents under it. `--meta` values belong to these inputs. |
| `cameo-ingest run -o OUT [options]` | Checks the inputs for changes, scans new or changed ones, builds every project without up-to-date output, and rebuilds the root files. |
| `cameo-ingest ingest -o OUT PATH... [options]` | `add`, then `run`. It is the default command: `cameo-ingest FILE -o OUT`. |
| `cameo-ingest status -o OUT [--json]` | Inputs and projects by status, failures, the latest run. Works while a run is going. |
| `cameo-ingest prune -o OUT [--dry-run]` | Drops missing inputs, and the projects that no remaining input contains. |
| `cameo-ingest scan -o OUT` | Finds the projects in the task list's inputs, and what each says about itself (save time, Cameo version, element ids), building nothing. |
| `cameo-ingest projects -o OUT [--csv FILE]` | Every project: status, save time, Cameo version, size, and every path where it was found. |
| `cameo-ingest groups -o OUT [--csv FILE]` | Versions of the same model, found by the element ids they share, newest first (see "Versions and removal"). |
| `cameo-ingest remove -o OUT TOKEN... [--dry-run]` / `restore` | Removes projects from the tree, and keeps them out of later runs while their inputs remain; `restore` undoes it. |
| `cameo-ingest export -o OUT [--workbook FILE] [--search-page FILE]` | Writes the catalog of the tree's models for people to search without tools: a workbook, a self-contained search page, or both (see "Searching without tools"). Apart from `run`, since it is a distribution step. |
| `cameo-ingest calibrate-vision -o OUT [--suite quick\|standard]` | Calibrates the sketches to the tree's vision model on demand, as the first run with a model does on its own (see "Calibrating sketches to the vision model"). |
| `cameo-ingest calibrate-text -o OUT` | Calibrates the part size to the tree's text model on demand, as the first run with a model does on its own (see "Calibrating the part size to the text model"). |
| `cameo-ingest config [show]` / `config set KEY VALUE` / `config unset KEY` | The tree's settings: `llm` (on or off), `text-model`, `vision-model`, `render`, `rag-files`, `rag-source`, `concurrency` and `max-calls`. Each can be set and unset, back to its default; setting one starts a tree, so a tree can be configured before its first input. |

- **Which tree.** Every command works on `-o OUT`; without it, on `$CAMEO_INGEST_TREE`; without
  that, on `./ingest_tree` in the working directory. (`CAMEO_INGEST_DEST`, before 0.20.2, is
  ignored, with a notice.)

- **Output directories.** A missing or empty directory starts a tree. A directory with
  `state.sqlite` is continued. Any other non-empty directory is refused.
- **Stopping and continuing.** A run can be stopped at any time (Ctrl-C, SIGTERM, a crash, a
  lost session). Work is committed as it finishes, and a project is published only when it
  is complete. `cameo-ingest run -o OUT` continues, reusing the sketches and LLM answers the
  stopped run already had.
- **Remembered settings.** A run's model, rendering and LLM flags (and the `--env` file, never
  its contents) become the tree's settings, so a later `run` needs no flags. A change of
  options, or a new tool version, rewrites the projects it affects; stored LLM answers are
  reused.
- **Inputs that change or disappear.** A changed file is scanned again. A missing file is
  flagged, and its projects are kept until `prune`.
- **Exit status.** 0 success; 2 usage or configuration error; 3 an input had no readable
  model; 4 some projects failed (the others are written); 5 the LLM endpoint check failed;
  130 interrupted.

## Configuration

LLM enrichment (package summaries, diagram and image descriptions) needs an explicit
choice: either name a model or pass `--no-llm`. With neither, the tool stops at once and
says how to configure one. When a model is named, one tiny request per model checks the
endpoint before any work starts, so a wrong key, URL or model name fails in seconds rather
than hours later (`--no-preflight` skips the check).

| Variable | Flag | Purpose |
|---|---|---|
| `CAMEO_INGEST_TREE` | `-o` | The output tree, when `-o` is not given; else `./ingest_tree`. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | | Any OpenAI-compatible endpoint, such as vLLM or Ollama serving gemma. |
| `CAMEO_INGEST_TEXT_MODEL`, then `OPENAI_MODEL` | `--text-model` | Model for package summaries. |
| `CAMEO_INGEST_VISION_MODEL` | `--vision-model` | Model for diagram and image descriptions. Defaults to the text model. |
| `CAMEO_INGEST_LLM_TIMEOUT` | `--llm-timeout` | Seconds per request (default 120). |
| `CAMEO_INGEST_LLM_RETRIES` | `--llm-retries` | Retries per request (default 2). |
| `CAMEO_INGEST_LLM_MAX_CALLS` | `--llm-max-calls` | Stop calling the LLM after N requests in a run (default: no limit). |

Flags take precedence over variables. `.env.example` lists the variables: copy it to `.env`,
which is gitignored, and pass `--env .env`. Variables already set in the environment take
precedence over the file, and the log names the variables loaded but never their values.

LLM responses are kept in an SQLite store, `OUT/.cache/llm.sqlite` (or `--cache-dir DIR`),
keyed by endpoint, model and a hash of the request, so re-runs are cheap and repeatable; each
response is committed on its own. A failed request is logged and skipped, and never fails the
ingest; after 3 consecutive failures, enrichment is switched off for the rest of the run.
`run.json` reports the calls made and, for every item left without generated text, why
(failed, budget, switched off, empty answer), plus how many inputs were cut short to fit the
prompt. The API key is never written to the outputs. Generated text is only reproducible
while the store is kept: a fresh store gets fresh answers from the model.

`--llm-replay FILE` answers every request from a recorded `llm.sqlite` and never uses the
network; a request with no recorded answer fails its project. The store holds request
hashes, not prompts, so a store recorded on public samples can be committed as a test
fixture.

### Progress, logs and speed

On a terminal, each phase (scanning inputs, building projects, and per project: parsing,
layouts, rendering, LLM requests, writing) shows a progress bar. Otherwise (a batch job, or
output redirected), a heartbeat line is logged every 30 s (`--heartbeat SECONDS`; 0 turns it
off), with the phase, how far it got and an estimate of the time left. `-v` adds a line per
phase and project; `-vv` adds debug detail, including the HTTP requests. `--log-file FILE`
writes the debug detail to a file, whatever the console shows.

`--llm-concurrency N` sends up to N LLM requests at once, with the same output as sending
them one by one. The default is 1, which suits a local server; hosted endpoints usually
accept more. It matters for large models: TMT made 2,933 requests (version 0.4.0), which took
1 h 17 min at `--llm-concurrency 8` against gemma-4 on DeepInfra, and would take several times
that one at a time. Summarizing its 36 packages of analysis results from digests (FU-022) has
since replaced 376 of those requests with 36. Rendering is the costliest step without an
LLM: about 40 s for TMT's 1,241 sketches and the module views of its 44 large diagrams
(`--no-render` skips them).

`--image-pixels N` is the pixel budget of sketches and of the images sent to the vision model:
by default the vision model's calibration (see "Calibrating sketches to the vision model"),
uncalibrated 645,120. `google/gemma-4-31B-it` on DeepInfra sees every image through 280 soft
tokens of 48 × 48 px, scaled to fill that area at the image's own aspect ratio, so sketches are
drawn to fill it exactly, with sides in multiples of 48, and larger images are scaled down to
it. Images go before the text in each request, as Google advises, unless calibration finds the
model reads better with them after (see `docs/research/gemma4-images-2026-09-30.md`).

Each sketch's request also explains the drawing conventions that sketch uses, one sentence each:
- number tags, and names cut short;
- nesting and frames;
- arrowheads and hollow triangles;
- trees, and containment trees;
- dashed dependencies, and association classes;
- pins and ports, and item flows;
- connector circles, fork and join bars, and sequence diagrams.

The sketches are ours, so we know what each mark means. With the guide, gemma-4 found 80% of
connections rather than 75%, and invented a third fewer
(`docs/research/sketch-ambiguities-2026-10-03.md`).

### Large diagrams and packages

A diagram with more shapes than the vision model reads well in one image is split into
modules that are connected and drawn close together
(`docs/research/diagram-partitioning-2026-09-30.md`). Uncalibrated, that is more than 25
shapes, into modules of 6 to 25; calibration sets the size for the model (below). Each module
is drawn and described on its own, and the diagram is then described as a whole from those
descriptions. `--diagram-modules N:MIN:MAX` (`N` = 0 never splits) sets the thresholds
explicitly; it is there for tuning, and the calibrated sizes should serve.

A package whose text is over the part size (12,000 characters, unless the text model's
calibration lowers it) is summarized in parts of 3,000 characters up to that size, grouped by
nesting, relationships and order. A single element whose text is longer than a part goes in
pieces, each headed by its title and a line such as "Piece: 2 of 3": nothing is cut. The
package is then summarized from its parts' summaries, through runs of at most 30 of them when
there are more. A package made mostly of instance specifications (at least 80%, such as
analysis results) is summarized instead in one request, from a digest of its instances by
classifier and slot. Short parts keep each request well within what the model reads evenly;
one long request loses the middle of a large package
(`docs/research/sandwiching-2026-09-30.md`).

### Calibrating sketches to the vision model

Sketches are drawn for the vision model that will describe them. The first run with a vision
model calibrates the sketches to it, before building:
- **What happens:** the run draws eye charts with the sketches' own font, number tags, lines
  and arrowheads, filled at random so that nothing can be guessed. It asks the model to read
  them, and derives the sizes to draw with.
- **Its cost:** about 90 requests, a few minutes on a hosted model, and about a dozen more to
  validate it.
- **Once per model and endpoint:** the result is recorded in the tree, and the answers stored,
  so later runs ask nothing. `--no-calibrate` skips it.

A run draws with sizes from, in order:
1. the tree's own settings: `--image-pixels`, `--diagram-modules`, `--sketch-*-px`,
   `--image-first` or `--image-last`;
2. the vision model's calibration;
3. the uncalibrated defaults, gemma-4's figures at DeepInfra for now
   (`docs/research/vision-calibration-gemma4-2026-10-03.md`):
   - 13 px text;
   - arrowheads with 10 px legs, and 1 px lines;
   - the pixel budget above;
   - modules of at most 25 shapes;
   - the image before the text.

A run without a vision model draws to the defaults: its sketches are for people.

**What the eye charts measure:**
- **The image's place:** six cards asked with the image both before and after the text. The
  rest are asked in the order that reads better; after the text only when that is clearly
  better.
- **Reading:** lines of codes and numbers at 6 to 16 px, in images of half to four times the
  budget. A threshold that grows with the image means the host shrinks images to a budget of
  its own.
- **Arrows:** numbered boxes joined by arrows, with heads of 6, 10 and 14 px and lines of 1 and
  2 px. The model lists each arrow from box to box, as a diagram's description must.
- **Density:** 9 to 36 boxes in one image, for the size of a large diagram's modules.

The reading decides the budget and the font. The arrows and density cards are then drawn at
that font and budget, so that nothing measured depends on the tree's current sizes. Each
recommendation comes from the measurements alone; keeping cached answers is no reason to keep
a value:

| Setting | Recommended |
|---|---|
| `--image-pixels` | For a host that shrinks images to a budget of its own: the largest image in which text reads as well as in the smallest. For a model that reads at native resolution: kept as configured, since there the budget is a matter of cost. |
| `--sketch-font-px` | 1.3 times the size read 90% of the time, at that budget. |
| `--sketch-arrow-px`, `--sketch-line-px` | The thinnest lines and smallest heads with 95% of arrows read the right way round. |
| `--diagram-modules` | Modules of up to the most shapes among which 90% of connections are found, either way round. |
| `--image-first`, `--image-last` | After the text only when that reads clearly better: by 5 points, and by twice the standard error. |

Where the eye charts decide nothing (no arrow size passes, say), the default serves.

**Validation on the tree's own sketches.** The eye charts measure what the model reads on
cards made for it. Validation then measures what it reads on the tree's own diagrams:
- **The sample:** up to 4 each of small diagrams (up to 9 shapes), medium ones and modules of
  large ones, the commonest diagram types first, from up to 4 of the tree's projects (under
  30 MB each).
- **The question:** each is drawn at the sizes the run will use, and the model is asked, from
  the image alone, for each shape's number and name and for every connection.
- **The scores,** against the diagram's own names and connections:
  - names read, word by word, as drawn;
  - connections found, either way round;
  - directions right;
  - connections invented: listed by the model, but not in the diagram (nesting read as a
    connection, say).

The run prints a line before building, for example "expected quality with acme/eye-vl: on 12
of the tree's sketches, 96% of names read, 91% of connections found, 83% of directions right".
Each score under 90%, and invented connections over 10%, get a warning naming what will
suffer, and the run carries on. A
description gets every name and connection as text too, so it should do better than what the
model reads from the image alone. `validation.md` beside the calibration's report has the
details, sketch by sketch, and `status` repeats the line.

**Reports and recalibrating:**
- **Reports:** each calibration writes `OUT/calibration/<model>-<date>/`:
  - the cards;
  - `results.json`, with every reply and score;
  - `report.md`, with the measurements and the recommendations;
  - the validation: its sketches, `validation.json` and `validation.md`.

  `status` lists the tree's calibrations, with their expected quality.
- **Recalibrating:** `cameo-ingest calibrate-vision -o OUT` calibrates on demand, after a host
  changes its limits, say. `--suite quick` (11 cards) checks a model without recording.
- **An incomplete calibration** (unanswered or mostly unreadable cards) is not recorded, and the
  run draws to the defaults, with a warning.
- **The cost of a change:** when a calibration changes the sizes, the next run draws every
  sketch again and asks again for its description, about one request per sketch.

A test that means to push a model past what it reads comfortably should say so, and set its
sizes from the calibration (for example, the font at the 90% threshold itself).

### Calibrating the part size to the text model

The first run with a text model also checks that it reads a part evenly, start to end (plan TC,
`docs/research/text-reading-2026-10-04.md`):
- **What happens:** it summarizes synthetic package text of 6,000, 12,000 and 24,000 characters,
  laid out in five groups, and answers five questions about each. Every name and figure is
  invented, so the scoring is exact: did the summary cover every group, and was every answer
  right?
- **Its cost:** 30 requests, once per model and endpoint; `--no-calibrate` skips it.
- **What it can change:** only lower the part size. A model that reads 12,000 characters evenly
  keeps 12,000. One that doesn't, or an endpoint that cuts long inputs, gets 6,000, with a
  warning when even 6,000 reads unevenly. Calibration never makes parts larger. Strong models
  read these cards evenly to 192,000 characters, but real packages are harder to summarize, and
  larger parts mean coarser part summaries.
- **The report:** `OUT/calibration/<model>-text-<date>/report.md`. `--part-chars N` sets the size
  by hand, and wins. `cameo-ingest calibrate-text -o OUT` calibrates again on demand, after a host
  changes its limits, say.

## Output

```
out/
  state.sqlite           task list and state: the authority for everything else (see below)
  INDEX.md               every project: name, token, counts, where it was found; failures
  manifest.json          every written project: token, directory, summary, files with sha256
  provenance.jsonl       one record per token: every input path, archive chain and --meta
                         value it was found with
  chunks.jsonl           all projects' chunks, with --meta values joined in
  CROSSREF.md            identifiers across every model: each requirement id, and each id in
                         names, text, documentation and tagged values, held by two elements or
                         more, with every place (also index:id chunks)
  rag/                   the same chunks as files, for RAG tools that read files but not JSONL
                         (see "Using the output for RAG"); --no-rag-files leaves it out
    text/<project>/      a .txt file per chunk, named <sha256 of its text>.txt
    meta/<project>/      each file's metadata, <sha256>.json, at the same path
  run.json               the latest run: times, command, options, LLM calls and outcomes
  calibration/           the vision models' calibrations: eye charts, replies, reports, and
                         their validation on the tree's own sketches
  quality/               spot-check sets of LLM requests and answers (`quality sample`)
  .cache/llm.sqlite      LLM answers
  by-sha256/<sha256>/    one project, named by the sha256 of its own bytes:
    README.md            overview: exporter version, counts, packages, diagrams, stereotypes
    LEDGER.md            compact listing, one line per item: packages, diagrams, requirements
                         (ID, text, satisfy/verify/derive links) and elements, grouped by package
    packages/<qn>.md     one file per package, one section per element (blocks, requirements,
                         activities, use cases…), with members, tagged values, relationships
                         in both directions (dependencies with their verbs), and "shown in
                         diagrams"; a large package's summary is followed by its parts'
                         summaries
    diagrams/<name>.md   diagram type, author and dates, a numbered legend of the shapes (by
                         nesting), connections from source to target, with the items they carry
                         and, for dependencies, how they read ("is derived from", "satisfies"),
                         what the shapes show inside them (a block's properties and operations,
                         a transition's trigger), and a table's rows or a matrix's description
    diagrams/<name>.png  a sketch redrawn from the layout data to the model's pixel budget: shapes
                         tagged with their legend numbers, arrows at the target, generalizations
                         drawn as Cameo's trees with one head at the parent; not a Cameo
                         rendering. For a large diagram, its modules are tinted and outlined
    diagrams/<name>.modules/M<k>.png
                         a large diagram's module k, cropped and drawn to the pixel budget,
                         the rest of the diagram faded; the page has a section per module
    images/, images.md   embedded raster images (attachment streams)
    tables/              elements, relationships, requirements, properties, tagged_values,
                         diagrams (.csv); diagram-tables/<name>.csv, each table that lists its
                         rows, as Cameo shows it
    index/               elements.jsonl (full structure), hierarchy.json, chunks.jsonl,
                         ids.jsonl, threads.jsonl and hierarchies.jsonl (the index across models,
                         the threads and the type hierarchies), catalog.jsonl (what `export`
                         writes out, one record per item)
```

### Provenance

A project's content has a stable token, `sha256:<hex>`, which names its directory. Every
artifact carries a trace that starts from it:

- Markdown files have JSON-valued YAML front matter with a `provenance` block.
- Every element section ends with a visible `trace:` locator.
- Every CSV row has a `trace` column.
- Every chunk has `metadata.content` (the token) and `metadata.provenance`.

A locator looks like this:

```
sha256:9ffd7a2c3b7f3fca!com.nomagic.magicdraw.uml_model.model#<xmi:id>@L796
```

It reads as: content hash → archive entry → `xmi:id` → line number. The `derivation` field
records how the text was produced:

- `extracted`: deterministic parsing.
- `rendered`: the PNG sketches.
- `llm`: generated text, with the model name, a prompt hash and the locators of the inputs.

Where a content was found is not part of its output: it is looked up by the token, in
`INDEX.md` (by file name and archive chain), `provenance.jsonl` (with full paths and `--meta`
values) and `state.sqlite`. A project directory therefore depends only on its content, the
options and the tool version: it is byte-identical whichever file or tree it came from, and
it isn't rewritten when the content turns up somewhere else. Of the root files, only
`provenance.jsonl`, `run.json`, `state.sqlite` and `rag/meta/` name local paths or times.

LLM-generated text is labelled "(generated by <model>; not part of the source model)". It is
emitted as separate `generated:*` chunks, so chunks of extracted text never mix sources. A
package's summary and a diagram's description say what it is about and what it is for, in
everyday words, without names, identifiers or exact values, which the extracted text holds
(0.20.0); each also gives itself a class (`metadata.about_class`: intent, structure, register,
flow, states…).

## Using the output for RAG

Load the root `chunks.jsonl` into your vector store: embed `text`, and keep `metadata` as
filterable fields.

**If your RAG tool reads files rather than JSONL,** point it at `rag/text/` alone, not at the
whole tree: the tree also holds Markdown pages, JSON indexes and CSV tables, which would be
ingested beside the chunks. Measured on the fictional questions
(`docs/research/windows-over-pages-2026-10-05.md`):
- **the pages alone** found answers far less often: e5-large's MRR@10 fell from 0.74 to 0.56, and
  reranked, from 0.76 to 0.66. Nearly half their text is links, front matter and trace lines, and
  a window cut from a page's middle doesn't say whose text it is;
- **the pages beside `rag/text/`** filled the top 10 with the same facts again (nDCG@10 down by
  0.06 to 0.12).
- **Folders:** one per project (`TMT-9ffd7a2c`, its name and the start of its token), and
  `_tree` for the projects ledger.
- **Files:** one `.txt` file per chunk, named by the sha256 of its text, so names never clash
  and change only when the text does.
- **Metadata:** `rag/meta/` has the same folders, with each file's metadata as `<sha256>.json`,
  for tools that take metadata per file. It is flat:
  - `title` (the chunk's heading), `kind` and `chunk_id`, which joins it to `chunks.jsonl`;
  - `project` and `project_token`;
  - `element_id`, `element_type`, `qualified_name` and `stereotypes`;
  - `page` (the Markdown page and anchor, in the tree) and `trace` (the locator);
  - `source_id`, the project's short id, and `source_file` and `source_files`: the input files
    it was found in, as full paths (with the members of any archives it was found inside);
  - `derivation` and, for generated text, `generated_by`;
  - `found_with` (the `--meta` values).
- **Sources:** `rag/meta/_sources.json` maps each project's short id (`9ffd7a2c`, as in its
  folder's name) to its name, token, input files and `--meta` values.
- **Provenance in the text too:** a tool may keep only a file's text, so the text names its
  source, briefly. File names can be very long, and files of the same name can hold different
  models, so chunk text never uses them:
  - **The heading** names the project by a label: the start of its file name and its short id,
    `(project ACME_Proposal_Vol3_Annex_B… [9ffd7a2c])`. Two files both called `model.mdzip`
    read `model [1a2b3c4d]` and `model [5e6f7a8b]`.
  - **A source line** ends each file, in one of two forms, set for the whole tree with
    `--rag-source` (a run rewrites `rag/` in the new form, without ingesting again):
    - `trace` (the default): `Source:` and the trace locator (content, archive entry, element and
      line);
    - `id`: `Source:` and short ids, `[9ffd7a2c:14d101e0b1d2]`, the project's and the chunk's,
      which `_sources.json` and `chunks.jsonl` resolve to files and locators.
  - **A last line,** `Found with:`, gives the `--meta` values of the inputs, if any. Adding each
    group's folder with its own value (`--meta group=...`) puts it in every chunk.

  Input file paths never go in the text: they can be longer than a whole window.
- **One window per file:** plain chunks are split so that a file, its heading and its source
  line fit in a 512-token embedding window, as estimated for e5 and bge. A tool that cuts files
  into 512-token windows then keeps the source with the text.
- **Updates:** a project's files are written again only when its chunks change.

**Chunk text is plain, for embedding** (from version 0.5.0; the Markdown chunks of earlier
versions, as on the pages, were retired in 0.6.0):
- **A heading on every chunk:** what the item is, its name, where it is and the project. For
  example, "Block Movement Channel in M-SysML::Facility::Material Handling System (project
  NIST_M-SysML [50ba80fd])". An unnamed requirement is titled by its id and the start of its text.
- **No apparatus:** link labels without their targets, and no trace line (the metadata keeps
  the provenance).
- **Parts that fit a 512-token window:** text that won't fit is split into parts, each
  repeating the heading, so that every part says whose text it is. The budget is in tokens, as
  estimated for e5 and bge (text full of ids makes two or three times more tokens per
  character than prose), and leaves room for the source line that files in `rag/` end with.

On the samples, plain chunks found answers as well as the Markdown or better, and better for
requirement ids, relationships and the smaller embedding models, at half the tokens to embed
(`docs/research/chunk-styles-2026-10-01.md`).

`metadata.kind` says what the chunk is:

| `kind` | Contents | Good for |
|---|---|---|
| `element`, `requirement`, `package`, `diagram`, `project` | One item: its documentation, requirement text, relationships and diagrams, then its members and tagged values | "What does X do?", "Why does requirement R exist?" |
| `element:details`, `package:details`, … | An item's members and tagged values, when they don't fit in its own chunk | "What ports does X have?", "What does X's tag T say?" |
| `ledger:requirements`, `ledger:diagrams`, `ledger:elements`, `ledger:packages` | One line per item for one package (split into parts of about 60 lines); `metadata.element_ids` lists the ids row by row | "Which requirements cover thermal control?", "List the activity diagrams", "Where does REQ-2-APS-0086 come from?" |
| `ledger:projects` | One line per project in the tree, with where it was found; `metadata.tokens` row by row | "Which models came from supplier X?" |
| `generated:*` | LLM text (`provenance.derivation.method = "llm"`): what a package or diagram is about and for, a module of a large diagram described, an image described. `metadata.about_class` is the class a summary or description gave itself | "Where is the filter backwash described?", "Which part of the model covers approved equipment?"; they help such questions, and cost questions after a single fact little (`docs/research/generated-for-search-2026-10-05.md`) |
| `generated:module_description` | One module of a large diagram. `metadata.covers` locates it: `number` and `of`, the legend's shape numbers (`shapes`), `elements`, its `box` in diagram coordinates, the page `anchor` and the `image` | "What does this part of the activity do?" |
| `index:id` | An identifier (a requirement id, or an id cited in text) and every place it occurs, across every model in the tree: what holds it, how (its id, in its text, satisfies it, is derived from it…), a snippet, and the project's short id (`[9ffd7a2c]`). One entry per id held by two elements or more | "Which models address RWT-REG-002?", "What cites PCT-SYS-0302?" |
| `trace:thread` | A model's derivation tree from one requirement: what derives from it, level by level, with what satisfies, verifies or refines each | "Which tests verify the requirements derived from SN-02?" |
| `index:hierarchy` | A model's type hierarchy from one general: its kinds, level by level, each with its kind word and the first sentence of its documentation (`HIERARCHIES.md` has them for reading) | "What kinds of vehicle detector does the model define?" |
| `generated:module_summary` | One part (or run of parts) of a large package. `metadata.covers` gives `number` to `last` of `of`, the `elements` it covers and the page `anchor` | "Which part of the requirements covers pointing?" |

In the root `chunks.jsonl`, `metadata.source_metadata` holds the `--meta` values of every
input the content was found in, as lists (`{"program": ["XYZ"]}`), ready for filtering. The
per-project `index/chunks.jsonl` files leave them out, so they stay independent of inputs;
join them with `provenance.jsonl` on `metadata.content` when loading those instead.

Suggestions, roughly in order of value, measured on the samples where the numbers say so
(`docs/research/chunk-styles-2026-10-01.md`):

1. **Rerank.** A reranker (a cross-encoder, such as `bge-reranker-v2-m3`) reorders the top
   candidates by reading question and passage together. On the fictional questions, Qwen3's
   0.6B reranker (a stand-in of about that size) raised BM25's MRR from 0.55 to 0.79 when
   reranking its top 100, which matches vector search. It raised any hybrid's MRR to 0.82, the
   best of all. Behind keyword search, rerank the top 100; behind a hybrid, the top 30
   (`docs/research/rerankers-2026-10-01.md`).
2. **Add keyword search next to vector search** (hybrid retrieval, e.g. BM25). Embeddings
   handle identifiers such as `REQ-2-APS-0086` poorly: asked "What does requirement X state?",
   e5-large ranked the requirement first 5 times in 20, and BM25 20 times in 20. Fused, they
   put the answer in the top 10 for 98% of literal questions, against 83% for e5-large alone.
   Most vector stores support hybrid search. Weight the keywords below the vectors, though,
   or use them for queries that look like ids and names: fused at equal weight, they lowered
   bge-large's MRR on paraphrased questions from 0.74 to 0.52
   (`docs/research/fictional-projects-2026-10-01.md`).
3. **Pass five chunks or more to the LLM.** The first chunk retrieved answered 59% of natural
   questions with e5-large, and the first five 92%.
4. **Use a large embedding model.** e5-large and bge-large did about equally well, and far better
   than MPNet or MiniLM. e5's `query: ` and `passage: ` prefixes made no difference.
5. **Filter on metadata.** Restrict to `kind` (for example `ledger:*` for "list…" questions,
   or `requirement` for "why…" questions), `project`, `content`, `stereotypes`, or
   `source_metadata` fields such as the program or supplier.
6. **Route counting and exhaustive questions to the tables.** Top-k retrieval can't reliably
   answer "how many requirements are unverified?". A tool that runs SQL over `tables/*.csv`
   (e.g. DuckDB) can. The ledgers cover the cases in between.
7. **Cite with the trace.** Every chunk's `metadata.provenance.locator` names the content,
   entry, `xmi:id` and line, and `provenance.jsonl` maps its token to the files it came from.
   Ask the LLM to quote the locator so answers can be checked.

## Versions and removal

A folder of models collected over time holds several versions of the same model, under the same
name or another, and copies of each. Copies cost nothing, since a project is known by its
content and processed once. Versions are told apart by the tree's tools, and you choose which to
keep (plan PV, `docs/archive/plans/project-versions-2026-10-03.md`):

```sh
cameo-ingest add -o OUT path/to/models      # the task list
cameo-ingest scan -o OUT                    # find the projects; build nothing
cameo-ingest groups -o OUT                  # versions of the same model, newest first
cameo-ingest remove -o OUT 9ffd7a2c3b7f     # the older ones, once checked (the report suggests the line)
cameo-ingest run -o OUT                     # build what remains
```

- **How versions are found:** by the element ids they share. Cameo keeps an element's id across
  saves, so versions share most of theirs. A project id can't be used alone: a model made from a
  template keeps the template's, and a migrated model may get a new one.
- **Which is newest:** by the save time that Cameo writes in each file (`Records.properties`),
  which copying doesn't change. Without it, the dates inside the zip stand in, and the report
  says so.
- **What the report flags:**
  - a member with many elements the newest lacks: a fork from a common model, or much deleted
    since;
  - projects that share only some elements, such as two models made from one template, listed
    as related but not grouped.
- **Removal:** a removed project's output goes, and later runs leave it out even while its file
  is still in the task list, or turns up again elsewhere. Its LLM answers stay cached, so
  `restore` costs only the build.

## Searching without tools

`cameo-ingest export` writes the tree's models as a file that people search with ordinary
office tools, without Python, a database or the tree itself (plan KX,
`docs/archive/plans/keyword-export-2026-10-02.md`). The RAG finds things by meaning. Keyword search is
better at ids and names: embeddings almost never find a requirement by its id, and keyword
search does nine times in ten (`docs/research/retrieval-baseline-2026-10-01.md`).

```sh
cameo-ingest export -o OUT --workbook catalog.xlsx --search-page search.html
```

**The search page** is one HTML file. A reader downloads it and opens it in a browser (Edge,
Chrome, Firefox, Safari): it loads nothing from the network and sends nothing anywhere, since
everything it shows is inside the file, compressed.
- **Loading:** it unpacks and indexes the catalog, with a progress bar and the time spent in
  each phase, and a Cancel button. It is then ready to search.
- **Searching:** results come as you type, ranked by BM25 with names and ids weighted above text.
  An id such as `REQ-1-OAD-1050` is one word. `prefix*` and `"a phrase"` work, and results can
  be filtered by model and type.
- **Reading an item:** its full text, as the RAG reads it, and its relationships as links to
  the related items. Its source is shown too, and the generated summaries about it, marked as
  such.
- **Linking:** `search.html#q=REQ-1` opens the page with that search.

SharePoint downloads HTML files rather than showing them, so readers save the page and open the
saved copy. Opened from inside a zip without extracting it first, it says so.

**The workbook** has one row per item, with its source: the path the model was found at
(which mirrors the SharePoint folders it was copied from) and its `--meta` values. Its sheets:

| Sheet | Holds |
|---|---|
| `About` | How to search it, and what was left out |
| `Find` | Type words; it lists the rows holding them all, ids and names first (Excel 2021, Microsoft 365 or Excel for the web) |
| `Search` | Every item, for Ctrl+F |
| `Requirements` | Requirements, with what satisfies, verifies, derives and refines them |
| `Identifiers` | Every id, and each place it appears, across models |
| `Elements` | Elements with a name or documentation |
| `Relationships` | Each relationship, as the pages word it |
| `Diagrams` | Diagrams, with their generated descriptions |
| `Summaries` | Generated summaries, marked with the model that wrote them |
| `Projects` | Each model: its source, metadata and counts |

**Sharing it.** Upload the workbook to SharePoint, where Excel for the web opens it in the
browser (up to 100 MB), or share it as a file for desktop Excel. Long text is cut in its
cells; the search page and the tree hold it whole.

**Other tools.** Obsidian and VS Code open the tree's pages as they are, Markdown with relative
links, and search all of them, for those who have the tree and one of these tools.

## State database

`state.sqlite` is plain SQLite, committed as work finishes, and meant to be queried:

| Table | Holds |
|---|---|
| `inputs` | The task list: path, status (`pending`, `done`, `failed`, `missing`), `--meta` values (JSON), size, mtime and sha256 as last processed, times, error. |
| `contents` | Each project's content: sha256, name (first seen), kind, size. |
| `sightings` | Where each content was found: input, input version (sha256), archive chain (JSON). |
| `projects` | Output state per content: status (`pending`, `working`, `written`, `failed`), tool version, options hash, summary, error. |
| `files` | Each written project's files with their sha256. |
| `runs` | Each run: times, command, outcome (`finished`, `interrupted`, `failed`), LLM report (JSON). |
| `settings` | The tree's remembered run settings. |
| `fingerprints` | Each project's save time, project id, exporter and element ids, which tell versions apart. |
| `removed` | Projects removed from the tree. |
| `calibrations` | Each model's calibration, by kind: vision or text. |
| `meta` | The schema version. |

Views: `current_sightings` (sightings in the current version of each input, with its path,
status and metadata) and `project_status` (every content, its output status and how often it
is currently seen). For example:

```sql
SELECT path, status, error FROM inputs WHERE status != 'done';            -- still to do, or failed
SELECT name, status, sightings FROM project_status ORDER BY name;         -- every project
SELECT path, chain, metadata FROM current_sightings WHERE name = 'TMT.mdzip';  -- where it came from
SELECT started, outcome, json_extract(llm, '$.calls') FROM runs ORDER BY started;
```

## Design

The documents for whoever maintains the tool are in `docs/` (`docs/README.md`):
- **How it works:** `docs/design/`, starting with `architecture.md` (the pipeline, the modules,
  state and publishing, security).
- **Why:** the architecture decision records in `docs/decisions/`. Among them: XMI read by its
  conventions alone, so that new Cameo versions and custom profiles need no code (ADR-0001);
  deterministic text as the authority, with LLM text labelled as such (ADR-0005); and sketches
  redrawn for the vision model and calibrated to it (ADR-0012, ADR-0015).
- **Evidence:** dated measurements in `docs/research/`.

## Known limitations

- **Tables, matrices and maps.** Cameo computes what they show whenever it shows them, and a
  model file stores only the rows a table lists itself:
  - **A table that lists its rows** is shown as Cameo shows it: its columns, sorted as configured,
    on its page, in `tables/diagram-tables/` and in chunks. A column only Cameo can compute (a
    custom expression, a property a profile derives) keeps its header, and the page names it.
  - **A table that finds its rows in a scope, a matrix, or a map** is shown without rows. Its page
    says so and why, and the workbook and search page say so too. A matrix's page says in words
    what it relates: its rows, its columns, what a cell marks and which way. A table's or map's
    page keeps its configuration.
- **Used projects** (`proxy.*` entries) aren't ingested as projects.
  - **References into them** read by the names in each model's cached copy of the used project.
  - **References to the standard UML and SysML libraries** read by their names (`String`,
    `Real`, `Block`).
  - **Still shown as written:** ids inside text, such as DocGen's view lists, table column
    settings and UUID-valued tagged values.
- **`.mdzipx` SVGs** aren't used. Their nested `.mdzip` is ingested as usual.
- **Attachments** (`BINARY-*` PNG, JPEG or PDF) are listed at project level but not
  linked to their owning elements. PDF and Office attachments aren't converted.
- **Chunk sizes.** Plain chunks are split to fit 512-token embedding windows, by an estimate
  of e5's tokens: 3 of 43,552 files in `rag/` for the samples ran over. A model with a smaller
  limit (MiniLM's 256) sees only the start of each. Tagged
  values are cut at 4,000 characters on pages, and hex-encoded images are described rather
  than shown.
- **Sequence diagrams and swimlanes** are split into modules like any other diagram.
- **Deleted diagrams.** Diagrams whose layout stream is missing still get a page, listing
  the elements known from the XMI.

What is planned, deferred or waiting on a decision is in `docs/roadmap.md`.

## Development

```sh
python3 scripts/fetch_samples.py [--small] [--strict]   # restore public sample models (~105 MB; --small ~11 MB)
uv run pytest            # synthetic fixtures, plus the samples under 5 MB (about 15 s); the search
                         # page's tests need Node, and its browser test Chrome, Chromium or Edge
                         # (each skipped when missing)
uv run pytest -m slow    # the large samples: TMT, TMT-2024x, SAF_FFDS, SAF_Plugin (about 1 min)
uv run pytest -m llm     # a real LLM endpoint, from the environment or .env (about 1 min, ~20 requests)
uv run ruff check src scripts tests   # lint, with the version the lock file pins
uv run python scripts/record_llm_fixture.py --env .env   # re-record the LLM replay fixture
uv run python scripts/make_fictional_projects.py out/eval/fiction   # the fictional projects, and their questions
uv run --extra eval python scripts/retrieval_eval.py TREE --env .env --questions out/eval/fiction/questions.jsonl --out DIR
                         # retrieval on those questions; the evaluation needs the extra, cameo-ingest[eval]
uv run --extra eval python scripts/compare_retrieval.py BEFORE AFTER   # two such runs, question by question
uv run python -m cameo_ingest.treediff BEFORE AFTER   # what a change did to an output tree
```

**Fictional projects.** Seven invented Cameo projects, ours to share, are built by
`cameo_ingest.evaluation.fiction` in the format Cameo writes. They grow in size and difficulty:
- **Kestrel Orchard Irrigation:** small, with planted facts whose every name and figure is
  invented, so that each question has one right answer;
- **Ashgrove Library Book Return Kiosk:** small and plain;
- **Riverbend Water Treatment Works:** a custom profile, near-duplicate instruments,
  requirements imported from DOORS, instances, a state machine and a constraint block; with
  two rival bids for the same works under the same file name, told apart by folder, whose
  answers lie across all three;
- **Ferrous Valley Level Crossing:** two variants whose blocks share their names, traceability
  three levels deep, a hazard log, and a fact found only in a diagram note;
- **Port Calder Traffic Signal System:** about 5,100 XMI ids, 150 intersections with
  near-duplicate names, and a type hierarchy of its equipment, three levels deep.

Each comes with questions whose answers are known by construction (254 in all, tagged by
difficulty; 210 without Kestrel, in `questions-ra.jsonl`, the set every comparison since
2026-10-02 uses), for the retrieval evaluation (`scripts/retrieval_eval.py --questions
out/eval/fiction/questions.jsonl`; `docs/design/evaluation.md`). The tests ingest every project and check that each answer
is where the key says it is.

The regular tests replay real model answers from `tests/fixtures/llm-replay.sqlite`, offline.
When a prompt, the fixture model (`tests/fixture_model.py`) or the page text changes, the
replay test fails with a `ReplayMiss`; record the fixture again with the script above.

The sample models in `samples/` are public third-party files and are gitignored; see
`samples/SOURCES.md` for their origins and licenses. `fetch_samples.py` pins each file's
sha256 and reports when upstream content has changed. Without samples, the sample tests
are simply not collected. Every sample run is checked for the same output invariants
(unique chunk ids and anchors, provenance on every file and row, traces that start from the
content, LLM text only in labelled chunks), and a few samples have pinned counts.

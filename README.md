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

`--image-pixels N` (default 645,120) is the pixel budget of sketches and of the images sent to the
vision model. `google/gemma-4-31B-it` on DeepInfra sees every image through 280 soft tokens of
48 × 48 px, scaled to fill that area at the image's own aspect ratio, so sketches are drawn to fill
it exactly, with sides in multiples of 48, and larger images are scaled down to it. Images go
before the text in each request, as Google advises (see
`docs/research/gemma4-images-2026-09-30.md`).

### Large diagrams and packages

A diagram with more than 25 shapes is too large to read in one image at that budget. It is
split into modules of 6 to 25 shapes that are connected and drawn close together
(`docs/research/diagram-partitioning-2026-09-30.md`). Each module is drawn and described on
its own, and the diagram is then described as a whole from those descriptions.
`--diagram-modules N:MIN:MAX` (default `25:6:25`; `N` = 0 never splits) changes the
thresholds; it is there for tuning, and the default should serve.

A package whose text is over 12,000 characters is summarized in parts of 3,000 to 12,000
characters, grouped by nesting, relationships and order. The package is then summarized from
its parts' summaries, through runs of at most 30 of them when there are more. A package
made mostly of instance specifications (at least 80%, such as analysis results) is summarized
instead in one request, from a digest of its instances by classifier and slot. Short parts
keep each request well within what the model reads evenly; one long request loses the middle
of a large package (`docs/research/sandwiching-2026-09-30.md`).

## Output

```
out/
  state.sqlite           task list and state: the authority for everything else (see below)
  INDEX.md               every project: name, token, counts, where it was found; failures
  manifest.json          every written project: token, directory, summary, files with sha256
  provenance.jsonl       one record per token: every input path, archive chain and --meta
                         value it was found with
  chunks.jsonl           all projects' chunks, with --meta values joined in
  run.json               the latest run: times, command, options, LLM calls and outcomes
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
                         and the table/matrix configuration
    diagrams/<name>.png  a sketch redrawn from the layout data to the model's pixel budget: shapes
                         tagged with their legend numbers, arrows at the target; not a Cameo
                         rendering. For a large diagram, its modules are tinted and outlined
    diagrams/<name>.modules/M<k>.png
                         a large diagram's module k, cropped and drawn to the pixel budget,
                         the rest of the diagram faded; the page has a section per module
    images/, images.md   embedded raster images (attachment streams)
    tables/              elements, relationships, requirements, properties, tagged_values,
                         diagrams (.csv)
    index/               elements.jsonl (full structure), hierarchy.json, chunks.jsonl
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
`provenance.jsonl`, `run.json` and `state.sqlite` name local paths or times.

LLM-generated text is labelled "(generated by <model>; not part of the source model)". It is
emitted as separate `generated:*` chunks, so chunks of extracted text never mix sources.

## Using the output for RAG

Load the root `chunks.jsonl` into your vector store: embed `text`, and keep `metadata` as
filterable fields. Each chunk is self-contained, with its project and package path in the
text. `metadata.kind` says what the chunk is:

| `kind` | Contents | Good for |
|---|---|---|
| `element`, `requirement`, `package`, `diagram`, `project` | Full description of one item, with its trace | "What does X do?", "Why does requirement R exist?" |
| `ledger:requirements`, `ledger:diagrams`, `ledger:elements`, `ledger:packages` | One line per item for one package (split into parts of about 60 lines); `metadata.element_ids` lists the ids row by row | "Which requirements cover thermal control?", "List the activity diagrams", "Where does REQ-2-APS-0086 come from?" |
| `ledger:projects` | One line per project in the tree, with where it was found; `metadata.tokens` row by row | "Which models came from supplier X?" |
| `generated:*` | LLM summaries and descriptions (`provenance.derivation.method = "llm"`) | Extra recall; weight or filter them separately |
| `generated:module_description` | One module of a large diagram. `metadata.module` locates it: `number` and `of`, the legend's shape numbers (`shapes`), `elements`, its `box` in diagram coordinates, the page `anchor` and the `image` | "What does this part of the activity do?" |
| `generated:module_summary` | One part (or run of parts) of a large package. `metadata.part` gives `number` to `last` of `of`, the `elements` it covers and the page `anchor` | "Which part of the requirements covers pointing?" |

In the root `chunks.jsonl`, `metadata.source_metadata` holds the `--meta` values of every
input the content was found in, as lists (`{"program": ["XYZ"]}`), ready for filtering. The
per-project `index/chunks.jsonl` files leave them out, so they stay independent of inputs;
join them with `provenance.jsonl` on `metadata.content` when loading those instead.

Suggestions, roughly in order of value:

1. **Add keyword search next to vector search** (hybrid retrieval, e.g. BM25). Embeddings
   handle identifiers such as `REQ-2-APS-0086`, or part and block names, poorly; keyword
   search handles them exactly. Most vector stores support hybrid search.
2. **Filter on metadata.** Restrict to `kind` (for example `ledger:*` for "list…" questions,
   or `requirement` for "why…" questions), `project`, `content`, `stereotypes`, or
   `source_metadata` fields such as the program or supplier.
3. **Route counting and exhaustive questions to the tables.** Top-k retrieval can't reliably
   answer "how many requirements are unverified?". A tool that runs SQL over `tables/*.csv`
   (e.g. DuckDB) can. The ledgers cover the cases in between.
4. **Cite with the trace.** Every chunk's `metadata.provenance.locator` names the content,
   entry, `xmi:id` and line, and `provenance.jsonl` maps its token to the files it came from.
   Ask the LLM to quote the locator so answers can be checked.

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

```
runner: inputs ─► archive.discover ─► state (contents, sightings) ─► per project, in by-sha256/.work/:
                  (find projects,      xmi.parse_into / finalize ─► layout ─► diagrams.render_png ─►
                   hash each)          llm (optional, concurrent) ─► emit.ProjectWriter ─► publish ─► exports
```

- **Schema-agnostic XMI reading** (`xmi.py`). The parser relies only on XMI conventions:
  - a node with `xmi:id` is an element;
  - a node with `xmi:idref` or `href` is a reference;
  - a top-level node with a `base_*` attribute is a stereotype application.

  Attributes whose values are known ids become references in a second pass. As a result,
  metamodel changes between Cameo versions and custom profiles (such as TMT_Requirement,
  ReqIF or UAF) need no code changes. The parse is streaming (`iterparse`), so memory stays
  bounded: TMT (27 MB zipped, 71k elements) peaks at about 400 MB RSS and parses in about 3 s.
- **UML/SysML interpretation** (`semantics.py`) is a best-effort layer on top: documentation
  comments, multiplicities, value specifications, relationship ends, and requirement
  detection by stereotype name or `Id`/`Text` tags.
- **Rich text.** Cameo stores documentation, requirement text and string tags as HTML;
  `richtext.py` converts it to plain text.
- **Diagrams.** Layout streams hold presentation elements with an `elementID`, absolute
  `geometry` and link ends. They produce a deterministic node and edge list, which is the
  authoritative description. They also produce a PNG sketch that a vision model describes,
  with the node and edge list as context, so a weak model has less room to hallucinate.
- **Modules and parts** (`modules.py`). Large diagrams are split by Louvain community
  detection (`networkx`) on their connections, weighted by how close the shapes are drawn.
  Large packages are split the same way, with document order in place of geometry and
  sizes in characters. LLM requests run in rounds: modules and parts first, then the
  descriptions and summaries built from their answers.
- **State and publishing** (`state.py`, `runner.py`, `exports.py`). A project is built in a
  work directory and published by one rename plus one database transaction, so a project
  directory is always complete, and files a new version no longer produces disappear with
  the old directory. The root files are rebuilt from the database after every run.
- **Security.** Nothing is extracted to disk from archives. A zip-bomb budget applies (10 GB
  decompressed per input, and a 1000:1 ratio for large members). XML parsing has entity
  resolution and network access disabled. Encrypted ZIPs are rejected with an error.

## Known limitations and roadmap

- **Tables and matrices.** Their rows are computed by Cameo and aren't stored in the file,
  so only their configuration (scope, columns, element types) is emitted. The next step is
  to recompute the common cases, such as requirement tables and allocation matrices, from
  the model.
- **Used projects** (`proxy.*` entries) aren't ingested. References into them, such as
  SysML library types, show as raw ids or hrefs. The next step is to read the proxies only
  for labels.
- **`.mdzipx` SVGs.** The next step is to link them to diagrams and use them in place of
  the sketch, since they are real renderings. That needs a sample file and an SVG
  rasterizer such as `cairosvg` or `resvg`.
- **Attachments** (`BINARY-*` PNG, JPEG or PDF) are listed at project level but not yet
  linked to their owning elements. PDF and Office attachments aren't converted yet.
- **Chunk sizes.** Very large requirement or member sections aren't split; downstream chunkers
  may need to split them. Tagged values are cut at 4,000 characters on pages, and
  hex-encoded images are described rather than shown.
- **Sequence diagrams and swimlanes** are split into modules like any other diagram. Bands
  along the time axis, and activity partitions, would be better module boundaries.
- **Deleted diagrams.** Diagrams whose layout stream is missing still get a page, listing
  the elements known from the XMI.

## Development

```sh
python3 scripts/fetch_samples.py [--small] [--strict]   # restore public sample models (~105 MB; --small ~11 MB)
uv run pytest            # synthetic fixtures, plus the samples under 5 MB (about 15 s)
uv run pytest -m slow    # the large samples: TMT, TMT-2024x, SAF_FFDS, SAF_Plugin (about 1 min)
uv run pytest -m llm     # a real LLM endpoint, from the environment or .env (about 1 min, ~20 requests)
uv run python scripts/record_llm_fixture.py --env .env   # re-record the LLM replay fixture
```

The regular tests replay real model answers from `tests/fixtures/llm-replay.sqlite`, offline.
When a prompt, the fixture model (`tests/fixture_model.py`) or the page text changes, the
replay test fails with a `ReplayMiss`; record the fixture again with the script above.

The sample models in `samples/` are public third-party files and are gitignored; see
`samples/SOURCES.md` for their origins and licenses. `fetch_samples.py` pins each file's
sha256 and reports when upstream content has changed. Without samples, the sample tests
are simply not collected. Every sample run is checked for the same output invariants
(unique chunk ids and anchors, provenance on every file and row, traces that start from the
content, LLM text only in labelled chunks), and a few samples have pinned counts.

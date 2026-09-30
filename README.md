# cameo-ingest

Convert Cameo Systems Modeler / MagicDraw projects into provenance-tagged Markdown, CSV and
JSON for RAG ingestion, without needing Cameo itself. It tolerates project files saved by
MagicDraw 18.x through Cameo 2026x, and it has been checked against 14 public sample projects
(see `samples/SOURCES.md`).

```sh
uv sync
uv run cameo-ingest MODEL.mdzip -o out/ --meta program=XYZ --meta received=2026-09-01 \
    (--no-llm | --env .env | --text-model MODEL) \
    [--meta-file provenance.json] [--no-render] [--force] [-v]
```

Supported inputs are recognized by their content, so the file extension doesn't matter:

| Input | Handling |
|---|---|
| `.mdzip` | ZIP. The model is read from `com.nomagic.magicdraw.uml_model.model`, plus any `…uml_model.shared_model` (library and profile projects keep their content there). Diagram layouts come from `BINARY-*` entries. |
| `.rdzip` and bundles | Resource-manager ZIPs of ZIPs. Every nested project is found, up to 4 levels deep, and each gets its own output directory. |
| `.mdzipx` | Documented as an `.mdzip` plus one `.svg` per diagram. The nested `.mdzip` is ingested; the SVGs are not used yet (see Roadmap). No public sample exists to test against. |
| `.mdxml`, `.xmi` | A bare XMI document. |

## Configuration

LLM enrichment (package summaries, diagram and image descriptions) needs an explicit
choice: either name a model or pass `--no-llm`. With neither, the tool stops at once and
says how to configure one. When a model is named, one tiny request per model checks the
endpoint before parsing starts, so a wrong key, URL or model name fails in seconds rather
than hours later (`--no-preflight` skips the check).

| Variable | Flag | Purpose |
|---|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | | Any OpenAI-compatible endpoint, such as vLLM or Ollama serving gemma. |
| `CAMEO_INGEST_TEXT_MODEL`, then `OPENAI_MODEL` | `--text-model` | Model for package summaries. |
| `CAMEO_INGEST_VISION_MODEL` | `--vision-model` | Model for diagram and image descriptions. Defaults to the text model. |
| `CAMEO_INGEST_LLM_TIMEOUT` | `--llm-timeout` | Seconds per request (default 120). |
| `CAMEO_INGEST_LLM_RETRIES` | `--llm-retries` | Retries per request (default 2). |
| `CAMEO_INGEST_LLM_MAX_CALLS` | `--llm-max-calls` | Stop calling the LLM after N requests (default: no limit). |

Flags take precedence over variables. `.env.example` lists the variables: copy it to `.env`,
which is gitignored, and pass `--env .env`. Variables already set in the environment take
precedence over the file, and the log names the variables loaded but never their values.

LLM responses are kept in an SQLite store, `OUT/.cache/llm.sqlite` (or `--cache-dir DIR`),
keyed by endpoint, model and a hash of the request, so re-runs are cheap and repeatable; each
response is committed on its own, so a stopped run keeps what it got. A failed request is
logged and skipped, and never fails the ingest; after 3 consecutive failures, enrichment is
switched off for the rest of the run. `run.json` reports the calls made and, for every item
left without generated text, why (failed, budget, switched off, empty answer), plus how many
inputs were cut short to fit the prompt. The API key is never written to the outputs.
Generated text is only reproducible while the store is kept: a fresh store gets fresh
answers from the model.

`--llm-replay FILE` answers every request from a recorded `llm.sqlite` and never uses the
network; a request with no recorded answer fails its project. The store holds request
hashes, not prompts, so a store recorded on public samples can be committed as a test
fixture.

### Progress, logs and speed

On a terminal, each phase of each project (parsing, layouts, rendering, LLM requests,
writing) shows a progress bar. Otherwise (a batch job, or output redirected), a heartbeat
line is logged every 30 s (`--heartbeat SECONDS`; 0 turns it off), with the phase, how far it
got and an estimate of the time left. `-v` adds a line per phase and project; `-vv` adds
debug detail, including the HTTP requests. `--log-file FILE` writes the debug detail to a
file, whatever the console shows.

`--llm-concurrency N` sends up to N LLM requests at once, with the same output as sending
them one by one. The default is 1, which suits a local server; hosted endpoints usually
accept more. It matters for large models: at about 11 s per diagram description, TMT's
1,413 requests take about 4 hours one at a time.

## Output

```
out/
  manifest.json          source (file name, sha256, --meta), tool version, options, per-project
                         summary, failed projects, and every output file with its sha256
  run.json               this run only: id, start and finish times, source path, command line,
                         LLM calls and outcomes (which items got no generated text, and why)
  chunks.jsonl           all chunks from all projects: {id, title, text, metadata}
  LEDGER.md              the projects found in the source file, with counts
  <project>/
    README.md            overview: exporter version, counts, packages, diagrams, stereotypes
    LEDGER.md            compact listing, one line per item: packages, diagrams, requirements
                         (ID, text, satisfy/verify/derive links) and elements, grouped by package
    packages/<qn>.md     one file per package, one section per element (blocks, requirements,
                         activities, use cases…), with members, tagged values, relationships
                         in both directions, and "shown in diagrams"
    diagrams/<name>.md   diagram type and context, shapes (by nesting), connections, and the
                         table/matrix configuration
    diagrams/<name>.png  a sketch redrawn from the layout data (boxes, labels, paths), not a
                         Cameo rendering
    images/, images.md   embedded raster images (attachment streams)
    tables/              elements, relationships, requirements, properties, tagged_values,
                         diagrams (.csv)
    index/               elements.jsonl (full structure), hierarchy.json, chunks.jsonl
```

### Provenance

Every artifact carries a trace:

- Markdown files have JSON-valued YAML front matter with a `provenance` block.
- Every element section ends with a visible `trace:` locator.
- Every CSV row has a `trace` column.
- Every chunk has `metadata.provenance`.

The same input, options and tool version give byte-identical output, apart from `run.json`,
wherever the input file is stored. Outputs name the source by file name and sha256; its local
path is recorded only in `run.json`.

A locator looks like this:

```
sha256:9ffd7a2c3b7f3fca!bundle.rdzip!resource.zip!TMT.mdzip!com.nomagic.magicdraw.uml_model.model#<xmi:id>@L796
```

It reads as: source file hash → archive chain → entry → `xmi:id` → line number. The
`derivation` field records how the text was produced:

- `extracted`: deterministic parsing.
- `rendered`: the PNG sketches.
- `llm`: generated text, with the model name, a prompt hash and the locators of the inputs.

LLM-generated text is labelled "(generated by <model>; not part of the source model)". It is
emitted as separate `generated:*` chunks, so chunks of extracted text never mix sources.

## Using the output for RAG

Load `chunks.jsonl` into your vector store: embed `text`, and keep `metadata` as filterable
fields. Each chunk is self-contained, with its project, package path and source file in the
text. `metadata.kind` says what the chunk is:

| `kind` | Contents | Good for |
|---|---|---|
| `element`, `requirement`, `package`, `diagram`, `project` | Full description of one item, with its trace | "What does X do?", "Why does requirement R exist?" |
| `ledger:requirements`, `ledger:diagrams`, `ledger:elements`, `ledger:packages`, `ledger:projects` | One line per item for one package (split into parts of about 60 lines); `metadata.element_ids` lists the ids row by row | "Which requirements cover thermal control?", "List the activity diagrams", "Where does REQ-2-APS-0086 come from?" |
| `generated:*` | LLM summaries and descriptions (`provenance.derivation.method = "llm"`) | Extra recall; weight or filter them separately |

Suggestions, roughly in order of value:

1. **Add keyword search next to vector search** (hybrid retrieval, e.g. BM25). Embeddings
   handle identifiers such as `REQ-2-APS-0086`, or part and block names, poorly; keyword
   search handles them exactly. Most vector stores support hybrid search.
2. **Filter on metadata.** Restrict to `kind` (for example `ledger:*` for "list…" questions,
   or `requirement` for "why…" questions), `project`, `stereotypes`, or `source_metadata`
   fields such as the program or supplier.
3. **Route counting and exhaustive questions to the tables.** Top-k retrieval can't reliably
   answer "how many requirements are unverified?". A tool that runs SQL over `tables/*.csv`
   (e.g. DuckDB) can. The ledgers cover the cases in between.
4. **Cite with the trace.** Every chunk's `metadata.provenance.locator` names the source
   file, archive path, `xmi:id` and line. Ask the LLM to quote it so answers can be checked.

## Design

```
archive.discover ─► xmi.parse_into / finalize ─► layout.parse_layout ─► diagrams.render_png ─► llm (optional) ─► emit.ProjectWriter
(find projects)     (streaming, schema-agnostic    (BINARY-* <mdOwnedViews>)   (sketch)           (describe/summarize)   (md / csv / jsonl)
                     XMI → ModelIndex)
```

- **Schema-agnostic XMI reading** (`xmi.py`). The parser relies only on XMI conventions:
  - a node with `xmi:id` is an element;
  - a node with `xmi:idref` or `href` is a reference;
  - a top-level node with a `base_*` attribute is a stereotype application.

  Attributes whose values are known ids become references in a second pass. As a result,
  metamodel changes between Cameo versions and custom profiles (such as TMT_Requirement,
  ReqIF or UAF) need no code changes. The parse is streaming (`iterparse`), so memory stays
  bounded: TMT (27 MB zipped, 80k elements) peaks at about 400 MB RSS and takes about 20 s.
- **UML/SysML interpretation** (`semantics.py`) is a best-effort layer on top: documentation
  comments, multiplicities, value specifications, relationship ends, and requirement
  detection by stereotype name or `Id`/`Text` tags.
- **Rich text.** Cameo stores documentation, requirement text and string tags as HTML;
  `richtext.py` converts it to plain text.
- **Diagrams.** Layout streams hold presentation elements with an `elementID`, absolute
  `geometry` and link ends. They produce a deterministic node and edge list, which is the
  authoritative description. They also produce a PNG sketch that a vision model describes,
  with the node and edge list as context, so a weak model has less room to hallucinate.
- **Security.** Nothing is extracted to disk from archives. Zip-bomb limits apply. XML
  parsing has entity resolution and network access disabled. Encrypted ZIPs are rejected
  with an error.

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
- **Chunk sizes.** Very large requirement or tag sections aren't split; downstream chunkers
  may need to split them.
- **Deleted diagrams.** Diagrams whose layout stream is missing still get a page, listing
  the elements known from the XMI.

## Development

```sh
python3 scripts/fetch_samples.py [--small] [--strict]   # restore public sample models (~105 MB; --small ~11 MB)
uv run pytest            # synthetic fixtures, plus the samples under 5 MB (about 10 s)
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
(unique chunk ids and anchors, provenance on every file and row, LLM text only in labelled
chunks), and a few samples have pinned counts.

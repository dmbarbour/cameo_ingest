# Plan: labels for references outside a project, 2026-10-02

- **Status:** Done on 2026-10-02 (0.9.0). Approved that day ("labels ... are go whenever you think we're ready").
- **Step prefix:** `UL`, so steps are `UL-01`, `UL-02` and so on
- **Addresses:** the tentative plan "Labels from used projects" (plan index). References into
  used projects, such as SysML library types, show as raw ids: on pages, in chunks, in LLM
  inputs, and now in the catalog's exports.

## What a measurement of the samples found

A `--no-llm` tree of the samples and the fiction (27 projects) holds 12,987 references to
elements outside their project. 7,045 tagged values name such elements too.

| How the reference is written | References | How it reads today | What can name it |
|---|---|---|---|
| An OMG URI to the standard UML and SysML libraries, `http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML_dataType.Real` | 11,198, of 61 kinds | Its fragment: `SysML_dataType.Real`. NIST's 7,121 Strings read `_SysML_Libraries_PackageableElement-PrimitiveValueTypes_PackageableElement-String_PackageableElement` | The fragment itself: `Real`, `String`, `Block`, `Class` |
| A used project's element, `SAF_Profile.mdzip#_2021x_2_8710274_…` | 1,772 | Its raw id | The project's cached copy of the used project (`proxy.*`): every one of them |
| Other forms, such as `local:/PROJECT-…?resource=…#id` | 17 | Its raw id | The proxies, for 9 of them |

- **The proxies:** the `proxy.*` entries are XMI snapshots of the used projects, each element
  with its `xmi:id` and `name`. They hold the shared model (`…shared_umodel$dsnapshot`, 125
  entries in the samples, or `…umodel$dmodel$dsnapshot`, 6), and project metadata
  (`…metamodel$dproject$dsnapshot`, 122), which has no labels.
- **What isn't changed:** the archive scanner still skips proxies as models, so used projects
  are never ingested as projects of their own. Only names are read from them.

## Steps

| Step | What | Status |
|---|---|---|
| UL-01 | **Names from outside.** A module `external.py`:<br>- `proxy_names(project)`: the `xmi:id` → name of every named element in the project's shared-model proxies, read with `iterparse` (a proxy can be large; memory stays flat);<br>- `omg_name(uri)`: the readable part of an OMG URI's fragment. For `_SysML_Libraries_…-String_PackageableElement` it is `String`, for `SysML_dataType.Real` it is `Real`, for `SysML.Block` it is `Block`, for `_0` it is the file's library name (`UML`, `SysML`), and otherwise the fragment;<br>- `ModelIndex.external`, filled when a project is parsed.<br>`ModelIndex.label` and `semantics.label` read an outside reference's name from it, by the reference's fragment, before falling back to the fragment.<br>**Tests:** the fixture model gains a proxy entry and OMG references; each form is labelled; a proxy without names, or one that can't be read, leaves the fragment. | Done |
| UL-02 | **Where outside references show.** Everything that labels through `semantics.label` gains the names: pages, chunks, ledgers, the catalog. These need a change:<br>- tagged values that name an outside element (they show the value as written today);<br>- table and matrix configurations;<br>- a diagram shape whose element is outside the project (`shape_label`);<br>- the README's list of used projects, which can name each by its proxy's project name.<br>**Tests:** a tagged value and a diagram shape naming an outside element. | Done |
| UL-03 | **Checks:**<br>- a `--no-llm` tree against 0.8.3's, every difference classified, and a count of the raw ids that remain;<br>- the cost of the LLM requests that change, counted exactly with a run that may make no calls (`--llm-max-calls 0`, so that changed requests show as `skipped_budget`). Version 0.9.0. | Done (results below) |

## Results (2026-10-02)

**The tree:** a `--no-llm` tree of the samples and the fiction at 0.9.0 (`out/ul/after`), against
0.8.3's (`out/ul/before`).
- **Raw ids and library fragments** in chunk text fell from 17,056 to 3,268.
- **Fewer chunks,** 76,952 against 78,772: shorter text lets 588 of NIST's elements keep their
  members in their main chunk, without a "details" chunk, and other sections need fewer parts.
- **Every difference is explained,** element by element, comparing the lines of all of an
  element's chunks: an outside reference read by name (`String`, `Real`, `Brushless Motor`,
  `UML` for the UML library's root, `_0`), or the same lines in other parts.
- **Elsewhere:** 1,157 pages, 112 sketches and their SVGs changed, by the names drawn in
  shapes or their types.
- **What remains** is mostly data, not references:
  - NIST's `uid` values, 1,003 UUIDs;
  - table column ids, 665;
  - DocGen's view lists stored as text, 367;
  - help URLs, ReqIF and document identifiers.

**The LLM:** a run of the same inputs allowed no calls (`--llm-max-calls 0`, against a copy of
the answer store) answered 4,976 requests from the store.
- **Changed:** 958 asks, or 664 distinct requests, in TMT (338), NIST (127), SAF_FFDS and
  TMT-2024x (51 each), Library (32), SAF_Profile (29) and MDK_DocGen (15).
- **By template:** 240 module summaries, 186 diagram descriptions, 86 package summaries, 64
  module descriptions, 58 instance summaries, 20 package syntheses, 10 diagram syntheses.
- **Later rounds** built on these answers change too, so a live run would make about
  1,000–1,150 requests, about $1 at the rate of plan RA's CP4 run. That is under the halting
  threshold.

**The live run** (`out/ul/llm-live`, into the answer store) made 729 new requests, about $0.60,
fewer than estimated, since many of the changed asks were repeats. None failed, and 5,286
answers came from the store.
- **By template:** 240 module summaries, 186 diagram descriptions, 86 package summaries, 78
  package syntheses, 64 module descriptions, 58 instance summaries, 17 diagram syntheses.
- **The reading:** 271 package summaries changed. Those read side by side say the same, with
  real type names where the old had none ("a base_Class property of type Class").
- **Fresh exports** for the trial are in `out/kx/v090/`.

## When to stop and ask

- **The cost:** the changed requests would cost more than a few dollars at the next live run.
  Pages and chunks change regardless; only the LLM's re-asks cost money.
- **Wrong names:** a proxy names an element differently from what Cameo shows, for example a
  stale snapshot. Then the plan needs the maintainer's view on which to trust.

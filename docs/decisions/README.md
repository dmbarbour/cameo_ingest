# Decisions

Architecture decision records: why cameo-ingest is the way it is. Each is short: its context, the
decision, the evidence, and the consequences, with the IDs of the plans and reviews (now in
`docs/archive/`) where it was made. A record is never rewritten to say something else: a new one
supersedes it, and its status says so.

| ADR | Decision |
|---|---|
| [0001](0001-read-xmi-by-its-conventions.md) | Read XMI by its conventions, not by a metamodel |
| [0002](0002-content-addressed-resumable-tree.md) | Content-addressed projects in a resumable output tree |
| [0003](0003-reproducible-output-without-paths.md) | Per-project output is reproducible, and names no local path |
| [0004](0004-settings-and-options.md) | Tree settings, project options, and versions |
| [0005](0005-deterministic-text-is-the-authority.md) | The deterministic text is the authority; generated text is labelled |
| [0006](0006-plain-text-chunks.md) | Plain-text chunks for retrieval; pages stay Markdown |
| [0007](0007-rag-files-for-the-stack.md) | `rag/` files sized to one window, with sources by label |
| [0008](0008-structure-between-stages.md) | Sections built once as data; stages pass structure, not text |
| [0009](0009-versioned-prompt-templates.md) | Versioned prompt templates; no wording outside a version |
| [0010](0010-llm-store-session-and-endpoint.md) | Any OpenAI-compatible endpoint, chosen explicitly; answers kept by request |
| [0011](0011-ask-for-meaning-put-meaning-in-the-data.md) | Ask for meaning; put meaning in the data |
| [0012](0012-sketches-redrawn-for-the-model.md) | Sketches redrawn from the layout, numbered, at the model's budget |
| [0013](0013-modules-and-parts.md) | Large diagrams in modules, large packages in parts |
| [0014](0014-measurements-set-defaults.md) | Measurements set the defaults; caches are no reason to keep a value |
| [0015](0015-calibrate-to-the-configured-vision-model.md) | Calibrate sketches to the configured vision model |
| [0016](0016-validate-on-the-trees-own-sketches.md) | Validate on the tree's own sketches; warn and carry on |
| [0017](0017-tell-the-model-how-to-read-the-image.md) | Tell the model how to read the image |
| [0018](0018-generalization-trees-keep-member-heads.md) | Trees drawn with each member's head kept |
| [0019](0019-cross-model-index-and-threads.md) | An index of identifiers across models, and requirement threads |
| [0020](0020-versions-by-shared-element-ids.md) | Versions found by shared element ids; the tool reports, the maintainer removes |
| [0021](0021-exports-for-people-without-tools.md) | Exports for people without tools: a workbook and a self-contained page |
| [0022](0022-retrieval-evaluated-by-construction.md) | Retrieval evaluated by construction, with paired comparisons |
| [0023](0023-evaluation-as-library-code.md) | Evaluation code is library code; finished studies retire to a tag |
| [0024](0024-text-calibration-guards-the-part-size.md) | The text model's calibration guards the part size; it never enlarges it |

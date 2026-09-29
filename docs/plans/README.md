# Plans

Plans live in `docs/plans/<name>-<YYYY-MM-DD>.md`. Remediation that can be finished before
its review closes is written into the review itself (`docs/reviews/`) and is not listed
here.

## Index

None yet.

## Tentative

These plans are not yet written. The first one is required by the baseline review. The
others come from the roadmap in the top-level `README.md`.

- **Resumable, content-addressed ingest** (BASE-008R1, BASE-016R2, BASE-017R1, BASE-021R1).
  - **Identity:** identify each project by the sha256 of its own bytes. Process each
    content hash once, derive output locations and chunk IDs from that hash, and record
    every input path and archive chain where the content was seen, as provenance.
  - **State:** keep durable state in an SQLite database in the output directory. It holds
    the inputs, the content found in them, work status for each item, LLM results
    (replacing the JSON cache), and run history.
  - **Continuing:** a run continues into an existing output directory, including one left
    partly written, with no `--force` flag. Many inputs can share one output tree.
  - **Open question:** the plan must say what happens when the tool version or the options
    change between runs that share an output directory.
  - **Related work:**
    - The plan adopts the SQLite LLM store built during the baseline review. That store
      also serves as the replayable test fixture (BASE-022R5).
    - This plan affects reproducibility (BASE-015), progress reporting (BASE-018) and the
      LLM budget (BASE-019).
- **Recompute tables and matrices.** Cameo computes table and matrix rows when it displays
  them, and the rows are not stored in the file. Rebuild the common cases (requirement
  tables, allocation and dependency matrices) from the table configuration and the model.
  This depends on BASE-001 being fixed, because the configuration is currently dropped.
- **Labels from used projects.** References into used projects (the `proxy.*` entries), such
  as SysML library types, currently show as raw ids. Read the proxy snapshots for their
  labels only, without ingesting their content.
- **`.mdzipx` SVGs.** Link each diagram's SVG to its diagram and use it instead of the
  sketch. This needs a real sample and an SVG rasterizer such as `cairosvg` or `resvg`.
- **Attachments.** Link `BINARY-*` images and documents to the elements that own them, and
  convert PDF and Office attachments to text.
- **Chunk splitting.** Split very large requirement and tagged-value sections so that
  downstream chunkers don't have to.

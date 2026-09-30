# Plans

Plans live in `docs/plans/<name>-<YYYY-MM-DD>.md`. Remediation that can be finished before
its review closes is written into the review itself (`docs/reviews/`) and is not listed
here.

## Index

| Plan | Status | Addresses |
|---|---|---|
| [Resumable, content-addressed ingest](resumable-ingest-2026-09-29.md) | Draft; open questions for the maintainer | BASE-008R1, BASE-016R2, BASE-017R1, BASE-021R1 |

## Tentative

These plans are not yet written. They come from the roadmap in the top-level `README.md`.

- **Recompute tables and matrices.** Cameo computes table and matrix rows when it displays
  them, and the rows are not stored in the file. Rebuild the common cases (requirement
  tables, allocation and dependency matrices) from the table configuration and the model.
  BASE-001 is fixed, so the configuration is now read (scope, row types, columns).
- **Labels from used projects.** References into used projects (the `proxy.*` entries), such
  as SysML library types, currently show as raw ids. Read the proxy snapshots for their
  labels only, without ingesting their content.
- **`.mdzipx` SVGs.** Link each diagram's SVG to its diagram and use it instead of the
  sketch. This needs a real sample and an SVG rasterizer such as `cairosvg` or `resvg`.
- **Attachments.** Link `BINARY-*` images and documents to the elements that own them, and
  convert PDF and Office attachments to text.
- **Chunk splitting.** Split very large requirement and tagged-value sections so that
  downstream chunkers don't have to.

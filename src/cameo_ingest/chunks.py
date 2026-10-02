"""Chunk records: one id scheme, and the metadata every chunk carries, checked where chunks are
made (AR-015). Chunks stay plain dicts, ready for `chunks.jsonl`, in one key order: id, title,
text, metadata.

Every chunk's metadata has its `kind`, the `file` it is shown in, and its `provenance`: a
`locator` and a `derivation` with its `method`. A project's chunks also name the project
(`content`, `project`); the tree's own chunks (the index, threads, the projects ledger) are
assembled from several projects or about them all.
"""

from __future__ import annotations

from typing import Any

from .provenance import sha256_text

REQUIRED = ("kind", "file", "provenance")


def chunk_id(*parts: str) -> str:
    """A chunk's id: the start of the sha256 of what identifies it, its parts joined by "|"."""
    return sha256_text("|".join(parts))[:24]


def problems(chunk: dict[str, Any]) -> list[str]:
    """What a chunk record lacks, if anything."""
    out = [k for k in ("id", "title", "text") if not isinstance(chunk.get(k), str) or not chunk[k]]
    meta = chunk.get("metadata")
    if not isinstance(meta, dict):
        return [*out, "metadata"]
    out += [f"metadata.{k}" for k in REQUIRED if not meta.get(k)]
    prov = meta.get("provenance") or {}
    if not prov.get("locator"):
        out.append("metadata.provenance.locator")
    if not (prov.get("derivation") or {}).get("method"):
        out.append("metadata.provenance.derivation.method")
    if "content" in meta and not str(prov.get("locator", "")).startswith(str(meta["content"])[:23]):
        out.append("a trace that starts from the project's content (plan RI-02)")
    return out


def make(id_parts: tuple[str, ...], title: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """A chunk record, checked: its id from `id_parts` (see `chunk_id`)."""
    chunk = {"id": chunk_id(*id_parts), "title": title, "text": text, "metadata": metadata}
    bad = problems(chunk)
    if bad:
        raise ValueError(f"chunk {title!r} lacks {', '.join(bad)}")
    return chunk

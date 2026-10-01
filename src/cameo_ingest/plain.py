"""Plain chunk text for embedding (plan RE-08, decisions 6 and 11; `--chunk-style plain`).

The Markdown of the pages serves readers: links with their targets, trace lines, qualified names.
In a chunk, that apparatus fills the embedding window (45% of the characters, RE-01), and the
production stack cuts long chunks into windows that lose their heading. In the plain style:
- **text:** links reduced to their labels, no trace line (the metadata holds the provenance), no
  Markdown markers;
- **heading:** what the item is, its name (a requirement's id and text when it has no name),
  where it is (the last packages of its path) and the project;
- **meaning apart from structure:** an element's meaning (its requirement text, documentation,
  relationships, diagrams) in one chunk, its structural detail (members, tagged values) in a
  details chunk;
- **parts:** text longer than `BUDGET` characters is split at line boundaries, each part
  repeating the heading, so that every window says whose text it is.
"""

from __future__ import annotations

import re

from .text import md_plain, one_line

BUDGET = 1500  # characters per part: about 400 tokens of plain text, within a 512-token window
_LINK = re.compile(r"\[((?:[^\[\]\\]|\\.)*)\]\([^)]*\)")
_TRACE = re.compile(r"[ \t]*<sub>trace: `[^`]*`</sub>[ \t]*")
_BLOCK = re.compile(r"^\*\*([^*]+?)(?: \(([^)]*)\))?:\*\*\s*(.*)$")  # "**Documentation:**", "**Shapes (12), ...:**"
DETAIL_BLOCKS = ("Members", "Tagged values")


def plain(md: str) -> str:
    """Markdown as plain text: links to their labels, no trace lines, no emphasis or code marks."""
    text = _TRACE.sub("", md)
    text = _LINK.sub(r"\1", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<!\w)_\(([^)\n]*)\)_", r"(\1)", text)
    text = text.replace("```", "").replace("`", "")
    text = re.sub(r"^> ?", "", text, flags=re.MULTILINE)  # quoted requirement text
    text = md_plain(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def blocks(md: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """A section's header lines (the bullets under its title) and its blocks, in order, each a
    name and its lines; the title and trace lines are dropped."""
    header: list[str] = []
    out: list[tuple[str, list[str]]] = []
    for line in md.splitlines():
        if line.startswith("#") or _TRACE.fullmatch(line):
            continue
        m = _BLOCK.match(line)
        if m:
            out.append((m.group(1), [m.group(3)] if m.group(3) else []))
        elif out:
            out[-1][1].append(line)
        elif line.strip():
            header.append(line)
    return header, out


_BRACKET_ID = re.compile(r"^\s*\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\]\s*")  # "[REQ-1-OAD-0468] ..." (DOORS)


def requirement_title(name: str | None, rid: str | None, text: str | None) -> str:
    """A requirement's readable title: its name with its id; or, unnamed (as DOORS imports are),
    its id and the start of its text."""
    text = one_line(text or "")
    m = _BRACKET_ID.match(text)
    if m:  # the id in the text is the one people use; the Id tag is often a database number
        rid, text = m.group(1), text[m.end():]
    if name:
        return f"{name} ({rid})" if rid else name
    start = text if len(text) <= 90 else text[:89].rsplit(" ", 1)[0] + "…"
    return f"{rid}: {start}" if rid and start else rid or start or "(unnamed)"


def where(qualified_name: str, project: str) -> str:
    """'in A::B::C (project X)': the last three packages of the owner's path, and the project."""
    owner = qualified_name.rsplit("::", 1)[0] if "::" in qualified_name else ""
    path = "::".join(owner.split("::")[-3:])
    return (f"in {path} " if path else "") + f"(project {project})"


def parts(heading: str, text: str, budget: int = BUDGET) -> list[str]:
    """`text` under `heading`, split at line boundaries into parts of at most about `budget`
    characters, each repeating the heading."""
    body = [line for line in text.splitlines()]
    out: list[list[str]] = [[]]
    size = 0
    for line in body:
        while len(line) > budget:  # a line too long for any part: cut it
            if out[-1]:
                out.append([])
            out[-1].append(line[:budget])
            out.append([])
            line, size = line[budget:], 0
        if size + len(line) > budget and out[-1]:
            out.append([])
            size = 0
        out[-1].append(line)
        size += len(line) + 1
    chunks = ["\n".join(p).strip() for p in out]
    chunks = [c for c in chunks if c]
    if len(chunks) <= 1:
        return [f"{heading}\n\n{chunks[0]}" if chunks else heading]
    return [f"{heading} (part {k} of {len(chunks)})\n\n{c}" for k, c in enumerate(chunks, 1)]


def section(md: str, heading: str) -> tuple[list[str], list[str]]:
    """An element's section (Markdown, as on its page) as plain parts: (meaning, details)."""
    header, bs = blocks(md)
    fields = [plain(h).removeprefix("- ") for h in header
              if not h.startswith(("- **Kind:**", "- **Qualified name:**"))]
    meaning = fields[:]
    detail: list[str] = []
    for name, lines in bs:
        text = plain("\n".join(lines))
        if not text:
            continue
        target = detail if name in DETAIL_BLOCKS else meaning
        inline = "\n" not in text and len(text) < 200 and not text.startswith("- ")  # lists keep their lines
        target.append(f"{name}: {one_line(text)}" if inline else f"{name}:\n{text}")
    # Always a meaning chunk: the heading alone (name, kind, place, project) is what a lookup finds.
    return parts(heading, "\n".join(meaning)), parts(f"{heading}, details", "\n".join(detail)) if detail else []

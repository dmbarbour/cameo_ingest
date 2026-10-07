"""The catalog as a workbook that people search with Excel alone (plan KX-03).

One row per item, across sheets by kind, each sheet an Excel Table (`xlsx_parts`, plan WT) with
columns to group, sort and filter by. Searching is Excel's own: Ctrl+F, and the tables' filters.
(A sheet of search formulas, `Find`, took over 15 seconds on a 16 MB workbook without a sign of
work, and went in 0.24.2 with the `Search` sheet it searched, TR-007.) Text is written as text,
never as a formula, number or link, wrapped in rows of three lines, and long text is cut at
`LIMITS`. The workbook has no formulas, and stands alone.

XlsxWriter writes it row by row (constant memory), a project at a time, so memory stays flat
whatever the corpus. Its document properties are fixed, so the same catalog gives the same bytes.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import xlsxwriter

from .catalog import ProjectCatalog
from .text import plural, xml_safe

# Characters per cell, by sheet; Excel's own limit is 32,767.
LIMITS = {"search": 1_000, "requirements": 4_000, "elements": 2_000, "summaries": 8_000, "cell": 32_767}
MAX_ROWS = 1_048_575  # a sheet's rows below its header
ROW_HEIGHT = 45  # points: three lines of wrapped text a row; a double-click on the row's border shows it all

# Columns to group, sort and filter by (plan WT-04): `Newest` (the model's newest version, by
# lineage), `Package 1` to `3` (a package path's first levels), `Subject` (the suggested view's:
# a diagram's own, an element's or requirement's where most of its diagrams are), `Coverage` (what
# relates to a requirement), `Shows` (a diagram's shapes) and `Diagrams` (where an element is shown).
PACKAGES = [("Package 1", 24), ("Package 2", 24), ("Package 3", 24)]
SHEETS: dict[str, list[tuple[str, int]]] = {  # name -> columns (header, width)
    "Requirements": [("Id", 18), ("Database number", 10), ("Name", 40), ("Text", 80), ("Project", 28),
                     ("Newest", 9), ("Package", 40), *PACKAGES, ("Subject", 30), ("Coverage", 24),
                     ("Satisfied by", 30), ("Verified by", 30), ("Derived from", 30), ("Derived into", 30),
                     ("Refined by", 30), ("Traces", 30), ("Other relationships", 40), ("Diagrams", 30),
                     ("Source", 40)],
    "Identifiers": [("Id", 18), ("Project", 28), ("Newest", 9), ("Element", 40), ("How", 22), ("Snippet", 80)],
    "Elements": [("Kind", 16), ("Name", 40), ("Where", 50), ("Project", 28), ("Newest", 9), *PACKAGES,
                 ("Subject", 30), ("Stereotypes", 20), ("Documentation", 80), ("Diagrams", 40), ("Listed in", 30)],
    "Relationships": [("Source", 40), ("Relationship", 18), ("Target", 40), ("Kind", 16), ("Project", 28),
                      ("Newest", 9)],
    "Diagrams": [("Name", 40), ("Type", 28), ("Owner", 40), ("Project", 28), ("Newest", 9), *PACKAGES,
                 ("Subject", 30), ("Elements shown", 10), ("Shows", 60), ("Table", 24),
                 ("Description (generated)", 80)],
    "Subjects": [("Model", 30), ("View", 30), ("Subject", 34), ("What it holds", 60), ("Diagram", 40),
                 ("Versions", 9)],
    "Summaries": [("Of", 40), ("What", 18), ("Project", 28), ("Newest", 9), ("Summary (generated)", 100),
                  ("Model", 24), ("Part", 10)],
    "Projects": [("Project", 30), ("Label", 30), ("Content", 24), ("Source", 60), ("Metadata", 30),
                 ("Saved", 20), ("Saved by", 24), ("Versions", 34), ("Lineage", 60), ("Requirements", 10), ("Elements", 10), ("Diagrams", 10), ("Packages", 10),
                 ("Relationships", 10), ("Summaries", 10), ("Left out", 40)],
}
REQUIREMENT_COLUMNS = {  # (relationship kind, direction) -> column of the Requirements sheet
    ("satisfy", "in"): "Satisfied by", ("verify", "in"): "Verified by", ("derivereqt", "out"): "Derived from",
    ("derivereqt", "in"): "Derived into", ("refine", "in"): "Refined by", ("trace", "out"): "Traces",
    ("trace", "in"): "Traces",
}


def cut(text: Any, limit: int) -> str:
    """Text for a cell: control characters dropped, cut to `limit` with "…"."""
    s = xml_safe("" if text is None else str(text))
    limit = min(limit, LIMITS["cell"])
    return s if len(s) <= limit else s[:limit - 1] + "…"


def saved_by(header: dict[str, Any]) -> str:
    sb = header.get("saved_by") or {}
    return " ".join(v for v in sb.values() if v) if isinstance(sb, dict) else str(sb)


class _Sheet:
    """A sheet of rows under a header, the header `top` rows down (a band above it for slicers,
    plan WT); text wrapped and top-aligned, in rows of `ROW_HEIGHT` (TR-007: legible as opened)."""

    def __init__(self, book: xlsxwriter.Workbook, name: str, columns: list[tuple[str, int]], header_fmt,
                 text_fmt=None, number_fmt=None, top: int = 0):
        self.ws = book.add_worksheet(name)
        self.columns = [c for c, _ in columns]
        self.top = top
        self.row = 0  # data rows written
        self.full = False
        self.text_fmt, self.number_fmt = text_fmt, number_fmt
        for i, (head, width) in enumerate(columns):
            self.ws.set_column(i, i, width)
            self.ws.write_string(top, i, head, header_fmt)
        self.ws.freeze_panes(top + 1, 0)

    def add(self, values: dict[str, Any], limit: int) -> None:
        if self.row >= MAX_ROWS - self.top:
            self.full = True
            return
        self.row += 1
        r = self.top + self.row
        self.ws.set_row(r, ROW_HEIGHT)
        for i, col in enumerate(self.columns):
            v = values.get(col)
            if isinstance(v, int) and not isinstance(v, bool):
                self.ws.write_number(r, i, v, self.number_fmt)
            elif v not in (None, ""):
                self.ws.write_string(r, i, cut(v, limit), self.text_fmt)

    def close(self) -> None:
        self.ws.autofilter(self.top, 0, self.top + max(self.row, 1), len(self.columns) - 1)


def write_workbook(path: Path, projects: Iterable[ProjectCatalog], version: str,
                   subjects: dict[str, Any] | None = None, facts: dict[str, dict[str, Any]] | None = None
                   ) -> dict[str, int]:
    """Write the workbook; returns the rows per sheet. `subjects`: the tree's `subjects.json`, if any
    (ADR-0031): the Subjects sheet, and each diagram's subject in the suggested view."""
    families = (subjects or {}).get("families", [])
    suggested: dict[tuple[str, str], str] = {}
    for f in families:
        view = next(v for v in f["views"] if v["id"] == f["default"])
        for s in view["subjects"]:
            for key in s["diagrams"]:
                for i in f["diagrams"].get(key, []):
                    suggested[f["tokens"][i], key] = s["label"]
    names: dict[tuple[str, str], str] = {}
    labels: dict[str, str] = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path), {"constant_memory": True, "strings_to_formulas": False,
                                           "strings_to_urls": False, "strings_to_numbers": False,
                                           "use_future_functions": True})
    book.set_properties({"title": "Catalog of the models", "comments": f"Made by cameo-ingest {version}",
                         "created": dt.datetime(2000, 1, 1)})  # noqa: DTZ001 (fixed, for reproducible bytes)
    head = book.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
    about = book.add_worksheet("About")  # first in the book, written last: it reports the totals
    text = book.add_format({"text_wrap": True, "valign": "top"})
    number = book.add_format({"valign": "top"})
    sheets = {name: _Sheet(book, name, cols, head, text, number) for name, cols in SHEETS.items()}
    left_out: Counter[str] = Counter()
    tables: Counter[str] = Counter()
    n_projects = 0
    for p in projects:
        n_projects += 1
        _project_rows(p, sheets, suggested, facts or {})
        labels[p.header.get("token") or ""] = p.label
        for r in p.records:
            if r["type"] == "diagram":
                names[p.header.get("token") or "", r["key"]] = r["name"]
        left_out.update(p.header.get("left_out", {}))
        tables.update(p.header.get("tables", {}))
    _subject_rows(families, names, labels, sheets["Subjects"])
    for s in sheets.values():
        s.close()
    rows = {name: s.row for name, s in sheets.items()}
    _about_sheet(about, book, rows, left_out, n_projects, version, [n for n, s in sheets.items() if s.full], tables)
    book.close()
    from .xlsx_parts import Table, add_parts

    add_parts(path, [Table(name, name, [c for c, _ in SHEETS[name]], n) for name, n in rows.items()])
    return rows


def _subject_rows(families: list[dict[str, Any]], names: dict[tuple[str, str], str], labels: dict[str, str],
                  sheet: _Sheet) -> None:
    """A row per model (by its newest project's label: rivals often share a file name), view, subject
    and diagram, the suggested view first."""
    for f in sorted(families, key=lambda f: (labels.get(f["tokens"][0], f["name"]).lower(), f["tokens"])):
        model = labels.get(f["tokens"][0], f["name"])
        for v in sorted(f["views"], key=lambda v: v["id"] != f["default"]):
            title = v["title"] + (" (suggested)" if v["id"] == f["default"] else "")
            subjects = [(s["label"], s.get("holds", ""), s["diagrams"]) for s in v["subjects"]]
            if v.get("unsorted"):
                subjects.append(("Not sorted yet", "The LLM gave no answer for these; the next run asks again.",
                                 v["unsorted"]))
            for label, holds, keys in subjects:
                rows = []
                for key in keys:
                    held = f["diagrams"].get(key, [])
                    name = next((names[f["tokens"][i], key] for i in held if (f["tokens"][i], key) in names), None)
                    if name is not None:
                        rows.append((name, len(held)))
                for name, n in sorted(rows):
                    sheet.add({"Model": model, "View": title, "Subject": label, "What it holds": holds,
                               "Diagram": name, "Versions": n}, LIMITS["search"])


_HOW = {"derived": "derived by others from", "built-on": "built on by others in", "root": "shares a root with",
        "branches": "a branch beside"}


def _lineage(fact: dict[str, Any], labels: dict[str, str]) -> tuple[str, str]:
    """The Versions and Lineage cells (plan LN-06)."""
    n = fact.get("versions", 1)
    versions = "" if n == 1 else ("newest of " if fact.get("rank") == 0 else f"version {n - fact['rank']} of ") + f"{n}"
    if n > 1 and fact.get("rank"):
        versions += f"; the newest: {labels.get(fact['family'], fact['family'][:15])}"
    notes = [f"{_HOW[how]} {labels.get(t, t[:15])}" for t, how in fact.get("kin", [])]
    notes += [f"shares a part with {labels.get(t, t[:15])}" for t in fact.get("related", [])]
    return versions, "; ".join(notes)


COVERAGE = (("Satisfied by", "satisfied"), ("Verified by", "verified"), ("Refined by", "refined"),
            ("Derived from", "derived"), ("Traces", "traced"))


def _packages(path: str | None) -> dict[str, str]:
    """`Package 1` to `3`: a package path's first three levels."""
    parts = (path or "").split("::") if path else []
    return {name: parts[i] for i, (name, _) in enumerate(PACKAGES) if i < len(parts)}


def _project_rows(p: ProjectCatalog, sheets: dict[str, _Sheet], suggested: dict[tuple[str, str], str],
                  facts: dict[str, dict[str, Any]]) -> None:
    project, source = p.label, p.source_text()
    token = p.header.get("token") or ""
    newest = "no" if facts.get(token, {}).get("rank") else "yes"
    described = {r["key"]: r["text"] for r in p.records
                 if r["type"] == "summary" and r["label"] == "Diagram description" and "module" not in r}
    shows: dict[str, list[str]] = {}  # a diagram's key -> the names of what it shows
    for r in p.records:
        if r["type"] in ("element", "requirement", "package"):
            for d, _ in r.get("diagrams") or []:
                shows.setdefault(d, []).append(r["name"])

    def subject_of(r: dict[str, Any]) -> str | None:
        """An item's subject in the suggested view: where most of its diagrams are (the first, on a tie)."""
        votes: dict[str, int] = {}
        for d, _ in r.get("diagrams") or []:
            if (lab := suggested.get((token, d))) is not None:
                votes[lab] = votes.get(lab, 0) + 1
        return max(votes, key=lambda k: votes[k]) if votes else None

    for r in p.records:
        t = r["type"]
        if t == "requirement":
            cols: dict[str, list[str]] = {}
            for _, kind, direction, phrase, _, other in r.get("relations", []):
                col = REQUIREMENT_COLUMNS.get((kind.lower(), direction))
                cols.setdefault(col or "Other relationships", []).append(other if col else f"{phrase} {other}")
            covered = [word for col, word in COVERAGE if cols.get(col)]
            sheets["Requirements"].add({"Id": r.get("id"), "Database number": r.get("db"), "Name": r["name"],
                                        "Text": r.get("text"), "Project": project, "Newest": newest,
                                        "Package": r.get("package"), **_packages(r.get("package")),
                                        "Subject": subject_of(r), "Coverage": ", ".join(covered) or "none",
                                        **{c: "; ".join(v) for c, v in cols.items()},
                                        "Diagrams": "; ".join(d[1] for d in r.get("diagrams", [])),
                                        "Source": source}, LIMITS["requirements"])
        elif t == "element":
            sheets["Elements"].add({"Kind": r.get("kind"), "Name": r["name"], "Where": r.get("where"),
                                    "Project": project, "Newest": newest, **_packages(r.get("package")),
                                    "Subject": subject_of(r), "Stereotypes": ", ".join(r.get("stereotypes", [])),
                                    "Documentation": r.get("text"),
                                    "Diagrams": "; ".join(d[1] for d in r.get("diagrams", [])),
                                    "Listed in": (r.get("listed_in") or [None, None])[1]}, LIMITS["elements"])
        elif t == "diagram":
            owner = (r.get("owner") or [None, None])[1]
            sheets["Diagrams"].add({"Name": r["name"], "Type": r.get("kind"), "Owner": owner,
                                    "Project": project, "Newest": newest, **_packages(r.get("package")),
                                    "Subject": suggested.get((token, r["key"])), "Elements shown": r.get("shapes"),
                                    "Shows": "; ".join(shows.get(r["key"], [])), "Table": r.get("table"),
                                    "Description (generated)": described.get(r["key"])}, LIMITS["summaries"])
        elif t == "relationship":
            sheets["Relationships"].add({"Source": r["source"][1], "Relationship": r["phrase"],
                                         "Target": r["target"][1], "Kind": r["kind"], "Project": project,
                                         "Newest": newest}, LIMITS["search"])
        elif t == "summary":
            part = f"M{r['module']}" if "module" in r else (f"{r['parts'][0]}–{r['parts'][1]}" if "parts" in r else "")
            sheets["Summaries"].add({"Of": r["of"][1], "What": r["label"], "Project": project, "Newest": newest,
                                     "Summary (generated)": r["text"], "Model": r.get("model"), "Part": part},
                                    LIMITS["summaries"])
    for rec in p.ids:
        sheets["Identifiers"].add({"Id": rec["term"], "Project": project, "Newest": newest, "Element": rec.get("what"),
                                   "How": rec.get("how"), "Snippet": rec.get("snippet")}, LIMITS["search"])
    c = p.header.get("counts", {})
    fact = facts.get(p.header.get("token") or "", {})
    versions, lineage = _lineage(fact, {t: f.get("label", t) for t, f in facts.items()})
    sheets["Projects"].add({"Project": p.header.get("name"), "Label": project, "Content": p.header.get("token"),
                            "Source": source, "Metadata": p.metadata_text(), "Saved": fact.get("saved"),
                            "Saved by": saved_by(p.header), "Versions": versions, "Lineage": lineage,
                            "Requirements": c.get("requirement", 0), "Elements": c.get("element", 0),
                            "Diagrams": c.get("diagram", 0), "Packages": c.get("package", 0),
                            "Relationships": c.get("relationship", 0), "Summaries": c.get("summary", 0),
                            "Left out": ", ".join(
                                ([f"tables not computed {n}"] if (n := p.header.get("tables", {}).get("not computed"))
                                 else []) + [f"{k} {n}" for k, n in sorted(p.header.get("left_out", {}).items(),
                                                                           key=lambda kv: -kv[1])[:8]])},
                           LIMITS["search"])


def _about_sheet(ws, book: xlsxwriter.Workbook, rows: dict[str, int], left_out: Counter[str], n_projects: int,
                 version: str, full: list[str], tables: Counter[str] | None = None) -> None:
    bold = book.add_format({"bold": True})
    title = book.add_format({"bold": True, "font_size": 14})
    ws.set_column(0, 0, 28)
    ws.set_column(1, 1, 110)
    lines: list[tuple[str, str, Any]] = [
        ("Catalog of the models", "", title),
        ("What this is", (f"Every requirement, diagram, package, named or documented element, relationship and "
                          f"generated summary of {plural(n_projects, 'model')}, one row each, made by "
                          f"cameo-ingest {version}."), bold),
        ("Search everything", ("Ctrl+F, then Options, Within: Workbook, and Find All: every match, listed, each a "
                               "click away."), bold),
        ("Filter and sort", ("Each sheet is a table: its header's buttons filter and sort. Type into a filter's "
                             "search box, or use Text Filters, Contains; filter several columns to narrow down. "
                             "Insert, Slicer adds buttons for a column's values."), bold),
        ("Group by", ("Newest: yes for the newest version of each model (filter it to see each model once). "
                      "Package 1 to 3: the first levels of an item's package. Subject: a diagram's subject in the "
                      "suggested view (see the Subjects sheet), and an element's or requirement's, where most of the "
                      "diagrams that show it are. Coverage: what relates to a requirement (satisfied, verified, "
                      "refined, derived, traced), or none."), bold),
        ("Read a row", "Rows show three lines; double-click a row's lower border to see all of it.", bold),
        ("Browse by subject", ("The Subjects sheet puts each model's diagrams in subjects, several ways (views): "
                               "filter Model and View, then read down Subject. The suggested view comes first; the "
                               "Diagrams sheet's Subject column is its subject. Subjects proposed by an LLM are "
                               "generated, not part of the models."), bold),
        ("Generated text", ("Summaries and diagram descriptions were written by an LLM, named in the Summaries "
                            "sheet; they are not part of the source models."), bold),
        ("Source", "Where each model was found when it was ingested: its path and the metadata given then.", bold),
        ("Long text", (f"Cut, with \u2026, at {LIMITS['requirements']:,} characters in Requirements, "
                       f"{LIMITS['elements']:,} in Elements, {LIMITS['summaries']:,} in Diagrams and Summaries, and "
                       f"{LIMITS['search']:,} elsewhere."), bold),
        ("", "", None),
        ("Rows", "", title),
    ]
    lines += [(name, f"{n:,}", bold) for name, n in rows.items()]
    if full:
        lines.append(("Sheets cut short", ", ".join(full) + f": Excel's limit of {MAX_ROWS:,} rows", bold))
    lines += [("", "", None), ("Left out", "", title),
              ("Why", ("Elements without a name, documentation or a chunk of their own (literals, unnamed pins and "
                       "the like), by kind:"), bold)]
    lines += [(k, f"{n:,}", bold) for k, n in left_out.most_common(20)]
    if tables:
        lines += [("", "", None), ("Tables, matrices and maps", "", title),
                  ("Shown with their rows", f"{tables.get('computed', 0):,}", bold),
                  ("Not computed", f"{tables.get('not computed', 0):,}", bold),
                  ("Why", ("Cameo computes what a table, matrix or map shows whenever it shows it, and a model file "
                           "stores only what the table lists itself. Tables that find their rows in a scope, and "
                           "matrices, are shown without rows; the Diagrams sheet's Table column says which."), bold)]
    for i, (a, b, fmt) in enumerate(lines):
        if a:
            ws.write_string(i, 0, a, fmt)
        if b:
            ws.write_string(i, 1, b)

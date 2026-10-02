"""The catalog as a workbook that people search with Excel alone (plan KX-03).

One row per item, across sheets by kind, with a `Search` sheet that holds every item, so that
Ctrl+F on one sheet finds anything wherever Find's scope ends, and a `Find` sheet whose
formulas list the rows that hold all the words typed into it (Excel 2021, Microsoft 365 and
Excel for the web). Text is written as text, never as a formula, number or link, and long
text is cut at `LIMITS`.

XlsxWriter writes it row by row (constant memory), a project at a time, so memory stays flat
whatever the corpus. Its document properties are fixed, so the same catalog gives the same bytes.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import xlsxwriter

from .catalog import ProjectCatalog
from .text import plural

# Characters per cell, by sheet; Excel's own limit is 32,767.
LIMITS = {"search": 1_000, "requirements": 4_000, "elements": 2_000, "summaries": 8_000, "cell": 32_767}
MAX_ROWS = 1_048_575  # a sheet's rows below its header
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # not allowed in the file's XML

SHEETS: dict[str, list[tuple[str, int]]] = {  # name -> columns (header, width)
    "Search": [("Type", 12), ("Kind", 16), ("Id", 16), ("Name", 40), ("Project", 28), ("Where", 50),
               ("Text", 80), ("Source", 40)],
    "Requirements": [("Id", 18), ("Database number", 10), ("Name", 40), ("Text", 80), ("Project", 28),
                     ("Package", 40), ("Satisfied by", 30), ("Verified by", 30), ("Derived from", 30),
                     ("Derived into", 30), ("Refined by", 30), ("Traces", 30), ("Other relationships", 40),
                     ("Diagrams", 30), ("Source", 40)],
    "Identifiers": [("Id", 18), ("Project", 28), ("Element", 40), ("How", 22), ("Snippet", 80)],
    "Elements": [("Kind", 16), ("Name", 40), ("Where", 50), ("Project", 28), ("Stereotypes", 20),
                 ("Documentation", 80), ("Listed in", 30)],
    "Relationships": [("Source", 40), ("Relationship", 18), ("Target", 40), ("Kind", 16), ("Project", 28)],
    "Diagrams": [("Name", 40), ("Type", 28), ("Owner", 40), ("Project", 28), ("Elements shown", 10),
                 ("Description (generated)", 80)],
    "Summaries": [("Of", 40), ("What", 18), ("Project", 28), ("Summary (generated)", 100), ("Model", 24),
                  ("Part", 10)],
    "Projects": [("Project", 30), ("Label", 30), ("Content", 24), ("Source", 60), ("Metadata", 30),
                 ("Saved by", 24), ("Requirements", 10), ("Elements", 10), ("Diagrams", 10), ("Packages", 10),
                 ("Relationships", 10), ("Summaries", 10), ("Left out", 40)],
}
REQUIREMENT_COLUMNS = {  # (relationship kind, direction) -> column of the Requirements sheet
    ("satisfy", "in"): "Satisfied by", ("verify", "in"): "Verified by", ("derivereqt", "out"): "Derived from",
    ("derivereqt", "in"): "Derived into", ("refine", "in"): "Refined by", ("trace", "out"): "Traces",
    ("trace", "in"): "Traces",
}


def cut(text: Any, limit: int) -> str:
    """Text for a cell: control characters dropped, cut to `limit` with "…"."""
    s = _CONTROL.sub("", "" if text is None else str(text))
    limit = min(limit, LIMITS["cell"])
    return s if len(s) <= limit else s[:limit - 1] + "…"


def saved_by(header: dict[str, Any]) -> str:
    sb = header.get("saved_by") or {}
    return " ".join(v for v in sb.values() if v) if isinstance(sb, dict) else str(sb)


class _Sheet:
    def __init__(self, book: xlsxwriter.Workbook, name: str, columns: list[tuple[str, int]], header_fmt):
        self.ws = book.add_worksheet(name)
        self.columns = [c for c, _ in columns]
        self.row = 0
        self.full = False
        for i, (head, width) in enumerate(columns):
            self.ws.set_column(i, i, width)
            self.ws.write_string(0, i, head, header_fmt)
        self.ws.freeze_panes(1, 0)

    def add(self, values: dict[str, Any], limit: int) -> None:
        if self.row >= MAX_ROWS:
            self.full = True
            return
        self.row += 1
        for i, col in enumerate(self.columns):
            v = values.get(col)
            if isinstance(v, int) and not isinstance(v, bool):
                self.ws.write_number(self.row, i, v)
            elif v not in (None, ""):
                self.ws.write_string(self.row, i, cut(v, limit))

    def close(self) -> None:
        self.ws.autofilter(0, 0, max(self.row, 1), len(self.columns) - 1)


def write_workbook(path: Path, projects: Iterable[ProjectCatalog], version: str) -> dict[str, int]:
    """Write the workbook; returns the rows per sheet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path), {"constant_memory": True, "strings_to_formulas": False,
                                           "strings_to_urls": False, "strings_to_numbers": False,
                                           "use_future_functions": True})
    book.set_properties({"title": "Catalog of the models", "comments": f"Made by cameo-ingest {version}",
                         "created": dt.datetime(2000, 1, 1)})
    head = book.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
    about = book.add_worksheet("About")  # first in the book, written last: it reports the totals
    find = book.add_worksheet("Find")
    sheets = {name: _Sheet(book, name, cols, head) for name, cols in SHEETS.items()}
    left_out: Counter[str] = Counter()
    n_projects = 0
    for p in projects:
        n_projects += 1
        _project_rows(p, sheets)
        left_out.update(p.header.get("left_out", {}))
    for s in sheets.values():
        s.close()
    rows = {name: s.row for name, s in sheets.items()}
    _find_sheet(find, book, head, rows["Search"])
    _about_sheet(about, book, rows, left_out, n_projects, version, [n for n, s in sheets.items() if s.full])
    book.close()
    return rows


def _project_rows(p: ProjectCatalog, sheets: dict[str, _Sheet]) -> None:
    project, source = p.label, p.source_text()
    described = {r["key"]: r["text"] for r in p.records
                 if r["type"] == "summary" and r["label"] == "Diagram description" and "module" not in r}
    for r in p.records:
        t = r["type"]
        if t in ("requirement", "element", "diagram", "package"):
            sheets["Search"].add({"Type": t.capitalize(), "Kind": r.get("kind"), "Id": r.get("id"), "Name": r["name"],
                                  "Project": project, "Where": r.get("where"), "Text": r.get("text"),
                                  "Source": source}, LIMITS["search"])
        if t == "requirement":
            cols: dict[str, list[str]] = {}
            for _, kind, direction, phrase, _, other in r.get("relations", []):
                col = REQUIREMENT_COLUMNS.get((kind.lower(), direction))
                cols.setdefault(col or "Other relationships", []).append(other if col else f"{phrase} {other}")
            sheets["Requirements"].add({"Id": r.get("id"), "Database number": r.get("db"), "Name": r["name"],
                                        "Text": r.get("text"), "Project": project, "Package": r.get("package"),
                                        **{c: "; ".join(v) for c, v in cols.items()},
                                        "Diagrams": "; ".join(d[1] for d in r.get("diagrams", [])),
                                        "Source": source}, LIMITS["requirements"])
        elif t == "element":
            sheets["Elements"].add({"Kind": r.get("kind"), "Name": r["name"], "Where": r.get("where"),
                                    "Project": project, "Stereotypes": ", ".join(r.get("stereotypes", [])),
                                    "Documentation": r.get("text"),
                                    "Listed in": (r.get("listed_in") or [None, None])[1]}, LIMITS["elements"])
        elif t == "diagram":
            owner = (r.get("owner") or [None, None])[1]
            sheets["Diagrams"].add({"Name": r["name"], "Type": r.get("kind"), "Owner": owner,
                                    "Project": project, "Elements shown": r.get("shapes"),
                                    "Description (generated)": described.get(r["key"])}, LIMITS["summaries"])
        elif t == "relationship":
            sheets["Relationships"].add({"Source": r["source"][1], "Relationship": r["phrase"],
                                         "Target": r["target"][1], "Kind": r["kind"], "Project": project},
                                        LIMITS["search"])
        elif t == "summary":
            part = f"M{r['module']}" if "module" in r else (f"{r['parts'][0]}–{r['parts'][1]}" if "parts" in r else "")
            sheets["Summaries"].add({"Of": r["of"][1], "What": r["label"], "Project": project,
                                     "Summary (generated)": r["text"], "Model": r.get("model"), "Part": part},
                                    LIMITS["summaries"])
            sheets["Search"].add({"Type": "Summary", "Kind": f"{r['label']} (generated)", "Name": r["of"][1],
                                  "Project": project, "Text": r["text"], "Source": source}, LIMITS["search"])
    for rec in p.ids:
        sheets["Identifiers"].add({"Id": rec["term"], "Project": project, "Element": rec.get("what"),
                                   "How": rec.get("how"), "Snippet": rec.get("snippet")}, LIMITS["search"])
    c = p.header.get("counts", {})
    sheets["Projects"].add({"Project": p.header.get("name"), "Label": project, "Content": p.header.get("token"),
                            "Source": source, "Metadata": p.metadata_text(), "Saved by": saved_by(p.header),
                            "Requirements": c.get("requirement", 0), "Elements": c.get("element", 0),
                            "Diagrams": c.get("diagram", 0), "Packages": c.get("package", 0),
                            "Relationships": c.get("relationship", 0), "Summaries": c.get("summary", 0),
                            "Left out": ", ".join(f"{k} {n}" for k, n in sorted(p.header.get("left_out", {}).items(),
                                                                                key=lambda kv: -kv[1])[:8])},
                           LIMITS["search"])


def _find_sheet(ws, book: xlsxwriter.Workbook, head, n: int) -> None:
    """Words in B2:D2, a project in B3 and a type in B4; the rows of `Search` that hold every
    word, those whose id or name holds the first word first."""
    ws.set_column(0, 0, 26)
    ws.set_column(1, 7, 24)
    note = book.add_format({"italic": True, "font_color": "#555555"})
    entry = book.add_format({"bg_color": "#FFF2CC", "border": 1})
    ws.write_string(0, 0, "Find rows of the Search sheet", book.add_format({"bold": True, "font_size": 14}))
    ws.write_string(1, 0, "Words (each must appear):", head)
    for col in (1, 2, 3):
        ws.write_blank(1, col, None, entry)
    ws.write_string(2, 0, "Project (optional):", head)
    ws.write_blank(2, 1, None, entry)
    ws.write_string(3, 0, "Type (optional):", head)
    ws.write_blank(3, 1, None, entry)
    ws.write_string(4, 0, "Needs Excel 2021, Microsoft 365 or Excel for the web; elsewhere, use Ctrl+F or the "
                          "Search sheet's filters. * and ? are wildcards.", note)
    for i, (col, _) in enumerate(SHEETS["Search"]):
        ws.write_string(5, i, col, head)
    last = n + 1
    rng = lambda c: f"Search!${c}$2:${c}${last}"  # noqa: E731

    def has(word: str) -> str:
        hits = "+".join(f"ISNUMBER(SEARCH({word},{rng(c)}))" for c in ("C", "D", "F", "G"))
        return f"IF({word}=\"\",1,({hits})>0)"

    keep = "*".join([has("$B$2"), has("$C$2"), has("$D$2"),
                     f"IF($B$3=\"\",1,{rng('E')}=$B$3)", f"IF($B$4=\"\",1,{rng('A')}=$B$4)"])
    score = f"ISNUMBER(SEARCH($B$2,{rng('C')}))+ISNUMBER(SEARCH($B$2,{rng('D')}))"
    formula = (f"=IF(AND($B$2=\"\",$C$2=\"\",$D$2=\"\"),\"Type a word in B2\","
               f"IFERROR(SORTBY(FILTER(Search!$A$2:$H${last},{keep}),FILTER({score},{keep}),-1),\"No match\"))")
    ws.write_dynamic_array_formula(6, 0, 6, 0, formula)
    ws.freeze_panes(6, 0)


def _about_sheet(ws, book: xlsxwriter.Workbook, rows: dict[str, int], left_out: Counter[str], n_projects: int,
                 version: str, full: list[str]) -> None:
    bold = book.add_format({"bold": True})
    title = book.add_format({"bold": True, "font_size": 14})
    ws.set_column(0, 0, 28)
    ws.set_column(1, 1, 110)
    lines: list[tuple[str, str, Any]] = [
        ("Catalog of the models", "", title),
        ("What this is", f"Every requirement, diagram, package, named or documented element, relationship and "
                         f"generated summary of {plural(n_projects, 'model')}, one row each, made by cameo-ingest {version}.",
         bold),
        ("Search everything", "Desktop Excel: Ctrl+F, then Options, Within: Workbook, and Find All. Where Find "
                              "searches only the open sheet, use the Search sheet: it holds every item.", bold),
        ("Find several words", "The Find sheet lists the rows that hold all the words typed into it, ids and names "
                               "first (Excel 2021, Microsoft 365 or Excel for the web).", bold),
        ("Filter a column", "Each sheet's header has filters: Text Filters, Contains, for one column.", bold),
        ("Generated text", "Summaries and diagram descriptions were written by an LLM, named in the Summaries "
                           "sheet; they are not part of the source models.", bold),
        ("Source", "Where each model was found when it was ingested: its path and the metadata given then.", bold),
        ("Long text", f"Cut at {LIMITS['search']:,} characters in Search, {LIMITS['requirements']:,} in "
                      f"Requirements, {LIMITS['elements']:,} in Elements and {LIMITS['summaries']:,} in Summaries; "
                      f"the search page and the output tree hold it whole.", bold),
        ("", "", None),
        ("Rows", "", title),
    ]
    lines += [(name, f"{n:,}", bold) for name, n in rows.items()]
    if full:
        lines.append(("Sheets cut short", ", ".join(full) + f": Excel's limit of {MAX_ROWS:,} rows", bold))
    lines += [("", "", None), ("Left out", "", title),
              ("Why", "Elements without a name, documentation or a chunk of their own (literals, unnamed pins and "
                      "the like), by kind:", bold)]
    lines += [(k, f"{n:,}", bold) for k, n in left_out.most_common(20)]
    for i, (a, b, fmt) in enumerate(lines):
        if a:
            ws.write_string(i, 0, a, fmt)
        if b:
            ws.write_string(i, 1, b)

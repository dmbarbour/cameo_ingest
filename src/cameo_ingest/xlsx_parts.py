"""Excel Tables, added to a written workbook (plan WT).

XlsxWriter writes the workbook in constant-memory mode, in which it makes no tables. A table is a
part of the file, added here after it is written (a `.xlsx` is a zip of XML parts):
`xl/tables/tableN.xml`, the sheet's `<tableParts>` and its relationship, and a content type; the
sheet's own autofilter (and its `_FilterDatabase` name) gives way to the table's.

Slicers were tried and set aside (plan WT-02; the maintainer: "easier to drop them and let users
who excel at Excel figure it out"): Excel opened them cleanly, and a table lets a user add one in
two clicks. The plan keeps what they took.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

from lxml import etree

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
TABLE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"
TABLE_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
# CT_Worksheet's children after <tableParts> (ISO/IEC 29500): it goes before them.
_AFTER_TABLE_PARTS = ("extLst",)


@dataclass
class Table:
    sheet: str  # the sheet's name
    name: str  # the table's name: letters, digits and underscores, unique in the workbook
    columns: list[str]  # the header row's text, left to right
    rows: int  # data rows below the header (at least one row is kept, empty if need be)
    style: str = "TableStyleMedium2"


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _rels_path(part: str) -> str:
    d, _, f = part.rpartition("/")
    return f"{d}/_rels/{f}.rels"


def _add_rel(rels: etree._Element, kind: str, target: str) -> str:
    used = {int(m.group(1)) for r in rels for m in [re.fullmatch(r"rId(\d+)", r.get("Id", ""))] if m}
    rid = f"rId{max(used, default=0) + 1}"
    etree.SubElement(rels, f"{{{PKG_REL}}}Relationship", Id=rid, Type=kind, Target=target)
    return rid


def _insert_before(root: etree._Element, new: etree._Element, before: tuple[str, ...]) -> None:
    """Place `new` before the first child named in `before` (local names), else last."""
    for i, child in enumerate(root):
        if etree.QName(child).localname in before:
            root.insert(i, new)
            return
    root.append(new)


def table_xml(t: Table, table_id: int) -> bytes:
    ref = f"A1:{_col(len(t.columns) - 1)}{max(t.rows, 1) + 1}"
    cols = "".join(f'<tableColumn id="{i}" name={quoteattr(c)}/>' for i, c in enumerate(t.columns, 1))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<table xmlns="{MAIN}" id="{table_id}" name={quoteattr(t.name)} displayName={quoteattr(t.name)} '
            f'ref="{ref}" totalsRowShown="0"><autoFilter ref="{ref}"/>'
            f'<tableColumns count="{len(t.columns)}">{cols}</tableColumns>'
            f'<tableStyleInfo name={quoteattr(t.style)} showFirstColumn="0" showLastColumn="0" '
            f'showRowStripes="1" showColumnStripes="0"/></table>').encode()


def _xml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def add_parts(path: Path, tables: list[Table]) -> None:
    """Rewrite the workbook at `path` with these tables, one a sheet at most, each from cell A1."""
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        infos = {i.filename: i for i in z.infolist()}
        parts = {name: z.read(name) for name in infos}
    wb = etree.fromstring(parts["xl/workbook.xml"])
    targets = {r.get("Id"): r.get("Target") for r in etree.fromstring(parts["xl/_rels/workbook.xml.rels"])}
    types = etree.fromstring(parts["[Content_Types].xml"])
    sheets = {s.get("name"): (i, "xl/" + targets[s.get(f"{{{REL}}}id")].lstrip("/").removeprefix("xl/"))
              for i, s in enumerate(wb.find(f"{{{MAIN}}}sheets"))}
    defined = wb.find(f"{{{MAIN}}}definedNames")
    for k, t in enumerate(tables, 1):
        index, part = sheets[t.sheet]
        root = etree.fromstring(parts[part])
        rels_path = _rels_path(part)
        rels = (etree.fromstring(parts[rels_path]) if rels_path in parts
                else etree.Element(f"{{{PKG_REL}}}Relationships", nsmap={None: PKG_REL}))
        af = root.find(f"{{{MAIN}}}autoFilter")  # the table filters now
        if af is not None:
            root.remove(af)
        if defined is not None:
            for dn in list(defined):
                if dn.get("name") == "_xlnm._FilterDatabase" and dn.get("localSheetId") == str(index):
                    defined.remove(dn)
        table_part = f"xl/tables/table{k}.xml"
        parts[table_part] = table_xml(t, k)
        etree.SubElement(types, f"{{{CT}}}Override", PartName="/" + table_part, ContentType=TABLE_CT)
        tp = etree.Element(f"{{{MAIN}}}tableParts", count="1")
        etree.SubElement(tp, f"{{{MAIN}}}tablePart", {f"{{{REL}}}id": _add_rel(rels, TABLE_REL, f"../tables/table{k}.xml")})
        _insert_before(root, tp, _AFTER_TABLE_PARTS)
        parts[part] = _xml(root)
        parts[rels_path] = _xml(rels)
    if defined is not None and not len(defined):
        wb.remove(defined)
    parts["xl/workbook.xml"] = _xml(wb)
    parts["[Content_Types].xml"] = _xml(types)
    stamp = infos["xl/workbook.xml"].date_time  # XlsxWriter's fixed time: the same catalog, the same bytes
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["[Content_Types].xml", *(p for p in parts if p != "[Content_Types].xml")]:
            info = zipfile.ZipInfo(name, date_time=infos[name].date_time if name in infos else stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, parts[name])
    tmp.replace(path)

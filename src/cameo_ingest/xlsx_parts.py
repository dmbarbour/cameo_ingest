"""Excel Tables and table slicers, added to a written workbook (plan WT-01).

XlsxWriter writes the workbook in constant-memory mode, in which it makes no tables, and it makes
no slicers in any mode. Both are parts of the file, added here after it is written: a `.xlsx` is
a zip of XML parts. For each table: `xl/tables/tableN.xml`, the sheet's `<tableParts>` and its
relationship, and a content type; the sheet's own autofilter (and its `_FilterDatabase` name)
gives way to the table's. For each table slicer (Excel 2013 and later, Excel for the web):

- `xl/slicerCaches/slicerCacheN.xml`, bound to the table and column by `x15:tableSlicerCache`;
- `xl/slicers/slicerN.xml`, the slicers of a sheet;
- `xl/drawings/drawingN.xml`, where they stand on the sheet, each a frame that requires `sle15`
  (with a plain shape for older versions);
- the worksheet's slicer list, the workbook's slicer caches, and a `Slicer_<name>` name, `#N/A`.

The extension identifiers are EPPlus's (`ExtLstUris`), a library whose slicers Excel accepts.
LibreOffice opens such a file and ignores the slicers; Excel is the test.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
X14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
X15 = "http://schemas.microsoft.com/office/spreadsheetml/2010/11/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
SLE = "http://schemas.microsoft.com/office/drawing/2010/slicer"
SLE15 = "http://schemas.microsoft.com/office/drawing/2012/slicer"

TABLE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"
DRAWING_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
SLICER_REL = "http://schemas.microsoft.com/office/2007/relationships/slicer"
SLICER_CACHE_REL = "http://schemas.microsoft.com/office/2007/relationships/slicerCache"
TABLE_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
DRAWING_CT = "application/vnd.openxmlformats-officedocument.drawing+xml"
SLICER_CT = "application/vnd.ms-excel.slicer+xml"
SLICER_CACHE_CT = "application/vnd.ms-excel.slicerCache+xml"

WORKSHEET_SLICERS = "{3A4CF648-6AED-40f4-86FF-DC5316D8AED3}"  # x15: a sheet's table slicers
WORKBOOK_SLICER_CACHES = "{46BE6895-7355-4a93-B00E-2C351335B9C9}"  # x15: the workbook's table slicer caches
TABLE_SLICER_CACHE = "{2F2917AC-EB37-4324-AD4E-5DD8C200BD13}"  # x15: a cache's table and column

EMU = 9525  # per pixel
SLICER_ROW_HEIGHT = 241300  # EMU: a slicer's buttons, as Excel makes them


@dataclass
class Table:
    sheet: str  # the sheet's name
    name: str  # the table's name: letters, digits and underscores, unique in the workbook
    columns: list[str]  # the header row's text, left to right
    rows: int  # data rows below the header (at least one row is kept, empty if need be)
    style: str = "TableStyleMedium2"
    top: int = 0  # rows above the header (a band for slicers)


@dataclass
class Slicer:
    table: str  # the table's name
    column: str  # the column it filters
    col: int  # where its top-left corner stands: a column and row of the sheet
    row: int
    width: int = 192  # pixels
    height: int = 260
    col_off: int = 0  # pixels, right of the column's left edge
    row_off: int = 0  # pixels, below the row's top edge
    caption: str | None = None
    columns: int = 1  # buttons across


@dataclass
class _Sheet:
    path: str  # the part, "xl/worksheets/sheet1.xml"
    tables: list[Table] = field(default_factory=list)
    slicers: list[Slicer] = field(default_factory=list)


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


def _next_rid(rels: etree._Element) -> str:
    used = {int(m.group(1)) for r in rels for m in [re.fullmatch(r"rId(\d+)", r.get("Id", ""))] if m}
    return f"rId{max(used, default=0) + 1}"


def _add_rel(rels: etree._Element, kind: str, target: str) -> str:
    rid = _next_rid(rels)
    etree.SubElement(rels, f"{{{PKG_REL}}}Relationship", Id=rid, Type=kind, Target=target)
    return rid


def _ensure_ext_list(root: etree._Element, tag: str) -> etree._Element:
    ext_list = root.find(f"{{{MAIN}}}extLst")
    if ext_list is None:
        ext_list = etree.SubElement(root, f"{{{MAIN}}}extLst")
    return ext_list


def _insert_before(root: etree._Element, new: etree._Element, before: tuple[str, ...]) -> None:
    """Place `new` before the first child named in `before` (local names, main namespace), else last."""
    for i, child in enumerate(root):
        if etree.QName(child).localname in before:
            root.insert(i, new)
            return
    root.append(new)


def table_xml(t: Table, table_id: int) -> bytes:
    ref = f"A{t.top + 1}:{_col(len(t.columns) - 1)}{t.top + max(t.rows, 1) + 1}"
    cols = "".join(f'<tableColumn id="{i}" name={quoteattr(c)}/>' for i, c in enumerate(t.columns, 1))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<table xmlns="{MAIN}" id="{table_id}" name={quoteattr(t.name)} displayName={quoteattr(t.name)} '
            f'ref="{ref}" totalsRowShown="0"><autoFilter ref="{ref}"/>'
            f'<tableColumns count="{len(t.columns)}">{cols}</tableColumns>'
            f'<tableStyleInfo name={quoteattr(t.style)} showFirstColumn="0" showLastColumn="0" '
            f'showRowStripes="1" showColumnStripes="0"/></table>').encode()


def slicer_cache_xml(name: str, source: str, table_id: int, column_id: int) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<slicerCacheDefinition xmlns="{X14}" xmlns:mc="{MC}" mc:Ignorable="x" xmlns:x="{MAIN}" '
            f'name={quoteattr(name)} sourceName={quoteattr(source)}>'
            f'<extLst><x:ext uri="{TABLE_SLICER_CACHE}" xmlns:x15="{X15}">'
            f'<x15:tableSlicerCache tableId="{table_id}" column="{column_id}"/></x:ext></extLst>'
            f'</slicerCacheDefinition>').encode()


def slicers_xml(slicers: list[tuple[str, str, str, int]]) -> bytes:
    """(name, cache, caption, columns) for each slicer of a sheet."""
    body = "".join(f'<slicer name={quoteattr(n)} cache={quoteattr(c)} caption={quoteattr(cap)}'
                   + (f' columnCount="{cols}"' if cols > 1 else "") + f' rowHeight="{SLICER_ROW_HEIGHT}"/>'
                   for n, c, cap, cols in slicers)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<slicers xmlns="{X14}" xmlns:mc="{MC}" mc:Ignorable="x" xmlns:x="{MAIN}">{body}</slicers>'
            ).encode()


def drawing_xml(frames: list[tuple[str, Slicer]]) -> bytes:
    """Each slicer's frame, anchored at its cell, with a plain shape for versions without slicers."""
    anchors = []
    for k, (name, s) in enumerate(frames, 2):
        x, y = 0, 0
        anchors.append(
            f'<xdr:oneCellAnchor><xdr:from><xdr:col>{s.col}</xdr:col><xdr:colOff>{s.col_off * EMU}</xdr:colOff>'
            f'<xdr:row>{s.row}</xdr:row><xdr:rowOff>{s.row_off * EMU}</xdr:rowOff></xdr:from>'
            f'<xdr:ext cx="{s.width * EMU}" cy="{s.height * EMU}"/>'
            f'<mc:AlternateContent xmlns:mc="{MC}"><mc:Choice xmlns:sle15="{SLE15}" Requires="sle15">'
            f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{k}" name={quoteattr(name)}/>'
            f'<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="{x}" y="{y}"/>'
            f'<a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="{SLE}">'
            f'<sle:slicer xmlns:sle="{SLE}" name={quoteattr(name)}/></a:graphicData></a:graphic>'
            f'</xdr:graphicFrame></mc:Choice><mc:Fallback><xdr:sp macro="" textlink=""><xdr:nvSpPr>'
            f'<xdr:cNvPr id="0" name=""/><xdr:cNvSpPr><a:spLocks noTextEdit="1"/></xdr:cNvSpPr></xdr:nvSpPr>'
            f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{s.width * EMU}" cy="{s.height * EMU}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:prstClr val="white"/></a:solidFill>'
            f'<a:ln w="1"><a:solidFill><a:prstClr val="green"/></a:solidFill></a:ln></xdr:spPr>'
            f'<xdr:txBody><a:bodyPr vertOverflow="clip" horzOverflow="clip"/><a:lstStyle/><a:p><a:r>'
            f'<a:rPr lang="en-US" sz="1100"/><a:t>{escape("A slicer for this table: it needs Excel 2013 or later.")}'
            f'</a:t></a:r></a:p></xdr:txBody></xdr:sp></mc:Fallback></mc:AlternateContent>'
            f'<xdr:clientData/></xdr:oneCellAnchor>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}">{"".join(anchors)}</xdr:wsDr>').encode()


# The worksheet's children that come after <drawing>, and after <tableParts> (ISO/IEC 29500, CT_Worksheet).
_AFTER_DRAWING = ("legacyDrawing", "legacyDrawingHF", "drawingHF", "picture", "oleObjects", "controls",
                  "webPublishItems", "tableParts", "extLst")
_AFTER_TABLE_PARTS = ("extLst",)


def add_parts(path: Path, tables: list[Table], slicers: list[Slicer] = ()) -> None:
    """Rewrite the workbook at `path` with these tables and slicers."""
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        parts = {i.filename: z.read(i) for i in z.infolist()}
        infos = {i.filename: i for i in z.infolist()}
    wb = etree.fromstring(parts["xl/workbook.xml"])
    wb_rels = etree.fromstring(parts["xl/_rels/workbook.xml.rels"])
    types = etree.fromstring(parts["[Content_Types].xml"])
    targets = {r.get("Id"): r.get("Target") for r in wb_rels}
    sheets: dict[str, _Sheet] = {}
    index: dict[str, int] = {}
    for i, s in enumerate(wb.find(f"{{{MAIN}}}sheets")):
        target = targets[s.get(f"{{{REL}}}id")]
        sheets[s.get("name")] = _Sheet("xl/" + target.lstrip("/").removeprefix("xl/"))
        index[s.get("name")] = i
    by_name = {t.name: t for t in tables}
    for t in tables:
        sheets[t.sheet].tables.append(t)
    for s in slicers:
        sheets[by_name[s.table].sheet].slicers.append(s)

    def override(part: str, ct: str) -> None:
        etree.SubElement(types, f"{{{CT}}}Override", PartName="/" + part, ContentType=ct)

    defined = wb.find(f"{{{MAIN}}}definedNames")
    table_ids = {t.name: k for k, t in enumerate(tables, 1)}
    n_drawing = sum(1 for p in parts if p.startswith("xl/drawings/drawing"))
    n_slicers = n_cache = 0
    cache_rids = []
    for sheet_name, sh in sheets.items():
        if not sh.tables and not sh.slicers:
            continue
        root = etree.fromstring(parts[sh.path])
        rels_path = _rels_path(sh.path)
        rels = etree.fromstring(parts[rels_path]) if rels_path in parts else etree.Element(f"{{{PKG_REL}}}Relationships")
        if sh.tables:
            af = root.find(f"{{{MAIN}}}autoFilter")  # the table filters now
            if af is not None:
                root.remove(af)
            if defined is not None:
                for dn in list(defined):
                    if dn.get("name") == "_xlnm._FilterDatabase" and dn.get("localSheetId") == str(index[sheet_name]):
                        defined.remove(dn)
            tp = etree.Element(f"{{{MAIN}}}tableParts", count=str(len(sh.tables)))
            for t in sh.tables:
                part = f"xl/tables/table{table_ids[t.name]}.xml"
                parts[part] = table_xml(t, table_ids[t.name])
                override(part, TABLE_CT)
                rid = _add_rel(rels, TABLE_REL, f"../tables/table{table_ids[t.name]}.xml")
                etree.SubElement(tp, f"{{{MAIN}}}tablePart", {f"{{{REL}}}id": rid})
            _insert_before(root, tp, _AFTER_TABLE_PARTS)
        if sh.slicers:
            if root.find(f"{{{MAIN}}}drawing") is not None:
                raise ValueError(f"sheet {sheet_name!r} has a drawing already: slicers would need to join it")
            n_drawing += 1
            n_slicers += 1
            frames, entries = [], []
            for s in sh.slicers:
                t = by_name[s.table]
                n_cache += 1
                cache = f"Slicer_{t.name}_{re.sub(r'[^A-Za-z0-9_]', '_', s.column)}"
                caption = s.caption or s.column
                name = f"{caption} ({t.name})"
                parts[f"xl/slicerCaches/slicerCache{n_cache}.xml"] = slicer_cache_xml(
                    cache, s.column, table_ids[t.name], t.columns.index(s.column) + 1)
                override(f"xl/slicerCaches/slicerCache{n_cache}.xml", SLICER_CACHE_CT)
                cache_rids.append(_add_rel(wb_rels, SLICER_CACHE_REL, f"slicerCaches/slicerCache{n_cache}.xml"))
                if defined is None:
                    defined = etree.Element(f"{{{MAIN}}}definedNames")
                    _insert_before(wb, defined, ("calcPr", "oleSize", "customWorkbookViews", "pivotCaches",
                                                 "smartTagPr", "smartTagTypes", "webPublishing", "fileRecoveryPr",
                                                 "webPublishObjects", "extLst"))
                dn = etree.SubElement(defined, f"{{{MAIN}}}definedName", name=cache)
                dn.text = "#N/A"
                frames.append((name, s))
                entries.append((name, cache, caption, s.columns))
            parts[f"xl/slicers/slicer{n_slicers}.xml"] = slicers_xml(entries)
            override(f"xl/slicers/slicer{n_slicers}.xml", SLICER_CT)
            parts[f"xl/drawings/drawing{n_drawing}.xml"] = drawing_xml(frames)
            override(f"xl/drawings/drawing{n_drawing}.xml", DRAWING_CT)
            drid = _add_rel(rels, DRAWING_REL, f"../drawings/drawing{n_drawing}.xml")
            _insert_before(root, etree.Element(f"{{{MAIN}}}drawing", {f"{{{REL}}}id": drid}), _AFTER_DRAWING)
            srid = _add_rel(rels, SLICER_REL, f"../slicers/slicer{n_slicers}.xml")
            ext_list = _ensure_ext_list(root, "extLst")
            ext = etree.SubElement(ext_list, f"{{{MAIN}}}ext", uri=WORKSHEET_SLICERS, nsmap={"x15": X15})
            sl = etree.SubElement(ext, f"{{{X14}}}slicerList", nsmap={"x14": X14})
            etree.SubElement(sl, f"{{{X14}}}slicer", {f"{{{REL}}}id": srid})
        parts[sh.path] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        parts[rels_path] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
        if rels_path not in infos:
            infos[rels_path] = zipfile.ZipInfo(rels_path, date_time=infos[sh.path].date_time)
    if defined is not None and not len(defined):
        wb.remove(defined)
    if cache_rids:
        ext_list = _ensure_ext_list(wb, "extLst")
        ext = etree.SubElement(ext_list, f"{{{MAIN}}}ext", uri=WORKBOOK_SLICER_CACHES, nsmap={"x15": X15})
        caches = etree.SubElement(ext, f"{{{X15}}}slicerCaches", nsmap={"x14": X14})
        for rid in cache_rids:
            etree.SubElement(caches, f"{{{X14}}}slicerCache", {f"{{{REL}}}id": rid})
    parts["xl/workbook.xml"] = etree.tostring(wb, xml_declaration=True, encoding="UTF-8", standalone=True)
    parts["xl/_rels/workbook.xml.rels"] = etree.tostring(wb_rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    parts["[Content_Types].xml"] = etree.tostring(types, xml_declaration=True, encoding="UTF-8", standalone=True)
    stamp = infos["xl/workbook.xml"].date_time
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["[Content_Types].xml", *[p for p in parts if p != "[Content_Types].xml"]]:
            info = zipfile.ZipInfo(name, date_time=infos[name].date_time if name in infos else stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, parts[name])
    tmp.replace(path)

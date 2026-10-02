"""Reading an .xlsx in tests without another dependency: it is a zip of XML."""

import re
import zipfile
from xml.etree import ElementTree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class Formula(str):
    """A cell's formula, as `=…`, to tell it from text that starts with `=`."""


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def sheets(path) -> dict[str, list[list[str | None]]]:
    """Every sheet's rows, as text (a formula as a `Formula`)."""
    with zipfile.ZipFile(path) as z:
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        out = {}
        for s in book.find("m:sheets", NS):
            xml = ElementTree.fromstring(z.read("xl/" + target[s.get(REL)].lstrip("/").removeprefix("xl/")))
            rows = []
            for row in xml.iter(f"{{{NS['m']}}}row"):
                cells: list[str | None] = []
                for c in row.findall("m:c", NS):
                    i = _col(c.get("r"))
                    cells += [None] * (i + 1 - len(cells))
                    f, v, t = c.find("m:f", NS), c.find("m:v", NS), c.get("t")
                    if f is not None:
                        cells[i] = Formula("=" + (f.text or ""))
                    elif t == "inlineStr":
                        cells[i] = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    elif t == "s":
                        cells[i] = shared[int(v.text)]
                    elif v is not None:
                        cells[i] = v.text
                rows.append(cells)
            out[s.get("name")] = rows
        return out

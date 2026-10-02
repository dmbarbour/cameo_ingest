"""Names for references outside a project (plan UL-01).

A model refers to elements it doesn't hold in two ways:
- **the standard UML and SysML libraries,** by OMG URI. The fragment names the element, if
  awkwardly: `SysML.xmi#SysML_dataType.Real`, or, in SysML 1.4 models,
  `…PrimitiveValueTypes_PackageableElement-String_PackageableElement`. `omg_name` reads it.
- **used projects,** by file and id (`SAF_Profile.mdzip#_2021x_…`). A project carries a cached
  copy of each used project's shared model (`proxy.*…uml_umodel…snapshot`), an XMI snapshot
  with each element's id and name, which `proxy_names` reads. Only names are read: a used
  project is never ingested as a project of its own.

`ModelIndex.external` holds the names, keyed by the reference's fragment (its id), and
`semantics.label` reads them.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from .archive import Project

log = logging.getLogger(__name__)

_LIBRARY = re.compile(r"/(\w+)\.xmi$")  # .../UML.xmi, .../SysML.xmi, .../PrimitiveTypes.xmi


def is_proxy_model(entry: str) -> bool:
    """A used project's shared model, cached in this project (not its metadata)."""
    return entry.startswith("proxy.") and "$duml_umodel$d" in entry and entry.endswith("snapshot")


def proxy_names(project: Project) -> dict[str, str]:
    """`xmi:id` → name of every named element in the project's cached used projects. A proxy
    that can't be read is skipped, with a note in the log."""
    names: dict[str, str] = {}
    for entry in project.entry_names:
        if not is_proxy_model(entry):
            continue
        try:
            with project.open(entry) as f:
                for _, el in etree.iterparse(f, events=("end",), huge_tree=True, resolve_entities=False,
                                             no_network=True, load_dtd=False, remove_comments=True, remove_pis=True):
                    name = el.get("name")
                    if name:
                        xid = next((v for k, v in el.attrib.items() if k.endswith("}id")), None)
                        if xid:
                            names.setdefault(xid, name)
                    el.clear(keep_tail=False)
        except Exception as e:  # a damaged or unusual proxy: its references keep their ids
            log.info("%s: cannot read used project %s: %s", project.display_name, entry, e)
    return names


def omg_name(uri: str) -> str | None:
    """The readable part of an OMG library reference, or None for another reference."""
    if "omg.org/spec/" not in uri or "#" not in uri:
        return None
    base, frag = uri.rsplit("#", 1)
    if frag.startswith("_SysML_Libraries"):  # SysML 1.4: …ValueTypes_PackageableElement-String_PackageableElement
        return frag.rsplit("-", 1)[-1].removesuffix("_PackageableElement")
    if frag in ("", "_0"):  # a library's root
        m = _LIBRARY.search(base)
        return m.group(1) if m else frag
    return frag.rsplit(".", 1)[-1]  # SysML_dataType.Real, SysML.Block


def external_label(names: dict[str, str], ref: str) -> str:
    """How a reference outside the project reads: its library or used project's name for it,
    else its id's last part."""
    frag = ref.rsplit("#", 1)[-1] if "#" in ref else ref
    return names.get(frag) or omg_name(ref) or frag

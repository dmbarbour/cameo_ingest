"""The synthetic Cameo project used by the tests, and by scripts/record_llm_fixture.py.

Changing anything here changes LLM requests, so the recorded replay fixture
(tests/fixtures/llm-replay.sqlite) must then be recorded again.
"""

import base64
import io
import zipfile

# Two names that share their first 140 characters, longer than the anchor's name part.
LONG = "Gravity calibration duration scenario for the operational blackbox entries " * 2

MODEL = """<?xml version='1.0' encoding='UTF-8'?>
<xmi:XMI xmlns:xmi='http://www.omg.org/spec/XMI/20131001' xmlns:uml='http://www.omg.org/spec/UML/20131001'
  xmlns:sysml='http://www.omg.org/spec/SysML/20181001/SysML'
  xmlns:MagicDraw_Profile='http://www.omg.org/spec/UML/20131001/MagicDrawProfile'
  xmlns:StandardProfile='http://www.omg.org/spec/UML/20131001/StandardProfile'>
 <xmi:Documentation><xmi:exporter>MagicDraw UML</xmi:exporter><xmi:exporterVersion>2024x</xmi:exporterVersion></xmi:Documentation>
 <uml:Model xmi:type='uml:Model' xmi:id='m1' name='Model'>
  <packagedElement xmi:type='uml:Package' xmi:id='p1' name='Structure'>
   <packagedElement xmi:type='uml:Class' xmi:id='b1' name='Drone'>
    <ownedComment xmi:type='uml:Comment' xmi:id='c1' body='A delivery drone.'><annotatedElement xmi:idref='b1'/></ownedComment>
    <ownedAttribute xmi:type='uml:Property' xmi:id='a1' name='battery' aggregation='composite' type='b2'>
     <lowerValue xmi:type='uml:LiteralInteger' xmi:id='a1l' value='1'/>
     <upperValue xmi:type='uml:LiteralUnlimitedNatural' xmi:id='a1u' value='2'/>
    </ownedAttribute>
    <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>
     <ownedDiagram xmi:type='uml:Diagram' xmi:id='d1' name='Drone BDD' ownerOfDiagram='b1'>
      <xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>
       <diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0'
          type='SysML Block Definition Diagram' umlType='Class Diagram'>
        <diagramContents><binaryObject streamContentID='BINARY-1'/></diagramContents>
       </diagram:DiagramRepresentationObject>
      </diagramRepresentation></xmi:Extension>
     </ownedDiagram>
    </modelExtension></xmi:Extension>
   </packagedElement>
   <packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>
   <packagedElement xmi:type='uml:Class' xmi:id='long1' name='LONG alpha'/>
   <packagedElement xmi:type='uml:Class' xmi:id='long2' name='LONG beta'/>
   <packagedElement xmi:type='uml:Class' xmi:id='odd' name='Cell [A*] &lt;v2&gt;'/>
  </packagedElement>
  <packagedElement xmi:type='uml:Package' xmi:id='p2' name='Requirements'>
   <packagedElement xmi:type='uml:Class' xmi:id='r1' name='Endurance'/>
   <packagedElement xmi:type='uml:Abstraction' xmi:id='s1' client='b2' supplier='r1'/>
   <packagedElement xmi:type='uml:Abstraction' xmi:id='rf1' client='b1' supplier='r1'/>
   <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>
    <ownedDiagram xmi:type='uml:Diagram' xmi:id='d2' name='Req Table' ownerOfDiagram='p2'>
     <xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>
      <diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0'
         type='Requirement Table' umlType='Class Diagram'>
       <diagramContents><binaryObject/></diagramContents>
      </diagram:DiagramRepresentationObject>
     </diagramRepresentation></xmi:Extension>
    </ownedDiagram>
   </modelExtension></xmi:Extension>
  </packagedElement>
 </uml:Model>
 <sysml:Block xmi:id='st1' base_Class='b1'/>
 <sysml:Block xmi:id='st2' base_Class='b2'/>
 <sysml:Requirement xmi:id='st3' base_Class='r1' Id='R-1'
   Text='&lt;html&gt;&lt;body&gt;&lt;p&gt;The drone &lt;b&gt;shall&lt;/b&gt; fly 30 min.&lt;/p&gt;&lt;/body&gt;&lt;/html&gt;'/>
 <sysml:Satisfy xmi:id='st4' base_Abstraction='s1'/>
 <StandardProfile:Refine xmi:id='st5' base_Abstraction='rf1'/>
 <MagicDraw_Profile:DiagramInfo xmi:id='st6' base_Diagram='d1' Author='tester'/>
 <MagicDraw_Profile:DiagramTable xmi:id='st7' base_Diagram='d2' displayMode='List' additionalElements='r1 b1'>
  <columnIds>QPROP:Element:name</columnIds>
 </MagicDraw_Profile:DiagramTable>
</xmi:XMI>
""".replace("LONG", LONG)

# The XML declaration is the one TMT uses; it pushes the root tag past byte 64 (BASE-013).
LAYOUT = """<?xml version='1.0' encoding='UTF-8' standalone='no'?>
<mdOwnedViews>
 <mdElement elementClass='Class' xmi:id='v1'><elementID xmi:idref='b1'/><geometry>10, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Class' xmi:id='v2'><elementID xmi:idref='b2'/><geometry>200, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Association' xmi:id='v3'><linkFirstEndID xmi:idref='v1'/><linkSecondEndID xmi:idref='v2'/>
  <geometry>110, 40; 200, 40; </geometry></mdElement>
</mdOwnedViews>
"""


# Fixed bytes rather than generated with Pillow: encoder changes across Pillow versions would
# change LLM request hashes and break replay (16x16 solid red and blue).
PNG_RED = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAF0lEQVR4nGP8z0AaYCJR/aiGUQ1DSAMAQC4BH2bjRnMAAAAASUVORK5CYII=")
PNG_BLUE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGNkYPjPQApgIkn1qIZRDUNKAwA+MAEfWiW9ygAAAABJRU5ErkJggg==")


def _entry(name: str) -> zipfile.ZipInfo:
    # A fixed timestamp keeps the archive, and so its sha256 and every locator, the same
    # from run to run.
    return zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))


def make_mdzip(model: str = MODEL, layout: str = LAYOUT, extra: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(_entry("com.nomagic.magicdraw.uml_model.model"), model)
        z.writestr(_entry("BINARY-1"), layout)
        z.writestr(_entry("BINARY-img1"), PNG_RED)
        z.writestr(_entry("BINARY-img2"), PNG_BLUE)
        z.writestr(_entry("Records.properties"), "#Compatibility entry\n")
        for name, text in (extra or {}).items():
            z.writestr(_entry(name), text)
    return buf.getvalue()


# References outside the project (plan UL): a SysML 1.4 library type, a SysML 1.6 one, an
# element of a used project (Lib.mdzip) as a part's type, as a tagged value and as a diagram's
# shape, and the cached copy of that used project that names it (a `proxy.*` entry).
STRING_14 = ("http://www.omg.org/spec/SysML/20150709/SysML.xmi#_SysML_Libraries_PackageableElement-"
             "PrimitiveValueTypes_PackageableElement-String_PackageableElement")
MODEL_EXTERNAL = MODEL.replace("""    <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>
     <ownedDiagram xmi:type='uml:Diagram' xmi:id='d1'""", f"""    <ownedAttribute xmi:type='uml:Property' xmi:id='x1' name='serial'><type href='{STRING_14}'/></ownedAttribute>
    <ownedAttribute xmi:type='uml:Property' xmi:id='x2' name='mass'>
     <type href='http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML_dataType.Real'/></ownedAttribute>
    <ownedAttribute xmi:type='uml:Property' xmi:id='x3' name='motor'><type href='Lib.mdzip#_lib_motor'/></ownedAttribute>
    <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>
     <ownedDiagram xmi:type='uml:Diagram' xmi:id='d1'""").replace("""<MagicDraw_Profile:DiagramInfo xmi:id='st6' base_Diagram='d1' Author='tester'/>""",
    """<MagicDraw_Profile:DiagramInfo xmi:id='st6' base_Diagram='d1' Author='tester'/>
 <StandardProfile:Trace xmi:id='st8' base_Class='b2'><supplier href='Lib.mdzip#_lib_cell'/></StandardProfile:Trace>""")
LAYOUT_EXTERNAL = LAYOUT.replace("</mdOwnedViews>", """ <mdElement elementClass='Class' xmi:id='v9'><elementID href='Lib.mdzip#_lib_motor'/>
  <geometry>400, 10, 100, 60</geometry></mdElement>
</mdOwnedViews>""")
PROXY = ("proxy.local__PROJECT$h0123456789abcdef_resource_com$dnomagic$dmagicdraw$duml_umodel$dshared_umodel"
         "$dsnapshot")
PROXY_XMI = """<?xml version="1.0" encoding="ASCII"?>
<xmi:XMI xmi:version="2.0" xmlns:xmi="http://www.omg.org/XMI" xmlns:uml="http://www.nomagic.com/magicdraw/UML/2.5.1.1">
  <uml:Package xmi:id="_lib_root" name="Parts Library">
    <packagedElement xmi:type="uml:Class" xmi:id="_lib_motor" name="Brushless Motor"/>
    <packagedElement xmi:type="uml:Class" xmi:id="_lib_cell" name="Lithium Cell"/>
  </uml:Package>
</xmi:XMI>
"""
EXTERNAL = {PROXY: PROXY_XMI}

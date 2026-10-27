"""CI helper: print each failed test from a JUnit XML report as a GitHub annotation (readable without login)."""
import sys
import xml.etree.ElementTree as ET

for case in ET.parse(sys.argv[1]).getroot().iter("testcase"):
    for bad in list(case.findall("failure")) + list(case.findall("error")):
        msg = (bad.get("message") or bad.text or "").strip().replace("\r", "").replace("\n", " ")[:900]
        print(f"::error title={case.get('classname')}.{case.get('name')}::{msg}")

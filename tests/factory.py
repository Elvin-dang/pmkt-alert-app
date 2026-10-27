"""Builds synthetic xlsx inputs for tests. No real business data here."""
import re
import zipfile
from pathlib import Path

import openpyxl


def write_xlsx(path: Path, sheets: dict[str, list[list]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(list(r))
    wb.save(path)
    return path


def break_dimension(path: Path) -> None:
    """Rewrite every worksheet's <dimension ref=...> to A1, like the real Activity Log export."""
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                data = re.sub(rb'<dimension ref="[^"]*"', b'<dimension ref="A1"', data)
            zout.writestr(item, data)
    tmp.replace(path)

"""Robust xlsx reading. Exports from the team's tools carry wrong <dimension> tags,
so every read-only sheet has its dimensions reset before iterating."""
from pathlib import Path

import openpyxl
import pandas as pd


def sheet_names(path: Path) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def read_sheet(path: Path, sheet: str | None = None, header_row: int = 1) -> pd.DataFrame:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        ws.reset_dimensions()
        rows = list(ws.iter_rows(min_row=header_row, values_only=True))
    finally:
        wb.close()
    if not rows:
        return pd.DataFrame()
    body = [r for r in rows[1:] if any(v is not None and v != "" for v in r)]
    width = max(len(r) for r in [rows[0], *body])
    head = tuple(rows[0]) + (None,) * (width - len(rows[0]))
    header = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(head)]
    body = [tuple(r[:width]) + (None,) * (width - len(r)) for r in body]
    return pd.DataFrame(body, columns=header)


def to_num(s: pd.Series) -> pd.Series:
    cleaned = s.map(lambda v: v.replace(",", "") if isinstance(v, str) else v)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0).astype(float)

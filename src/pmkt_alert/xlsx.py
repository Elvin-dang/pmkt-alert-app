"""Robust xlsx / csv reading. Exports from the team's tools carry wrong <dimension> tags,
so every read-only sheet has its dimensions reset before iterating. A .csv is one table (no sheets):
separator (, ; tab) and encoding (UTF-8 with or without BOM, else Windows-1258) are detected."""
import csv
from pathlib import Path

import openpyxl
import pandas as pd
from openpyxl.utils import get_column_letter


def is_csv(path: Path) -> bool:
    return Path(path).suffix.lower() == ".csv"


def _read_csv(path: Path) -> tuple[list[str], list[tuple[int, tuple]]]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:8192]
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        sep = ","
    rows = list(csv.reader(text.splitlines(), delimiter=sep))
    if not rows:
        return [], []
    header = [h.strip() or f"col{i}" for i, h in enumerate(rows[0])]
    body = [(n, tuple(v if v != "" else None for v in r)) for n, r in enumerate(rows[1:], 2) if any(x.strip() for x in r)]
    width = len(header)
    return header, [(n, r[:width] + (None,) * (width - len(r))) for n, r in body]


def sheet_names(path: Path) -> list[str]:
    if is_csv(path):
        return []
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _read(path: Path, sheet: str | None, header_row: int):
    """(header, [(excel_row, values), ...]) with fully empty rows dropped."""
    if is_csv(path):
        return _read_csv(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        ws.reset_dimensions()
        rows = list(ws.iter_rows(min_row=header_row, values_only=True))
    finally:
        wb.close()
    if not rows:
        return [], []
    body = [(header_row + i, r) for i, r in enumerate(rows[1:], 1) if any(v is not None and v != "" for v in r)]
    width = max(len(r) for r in [rows[0], *(r for _, r in body)])
    head = tuple(rows[0]) + (None,) * (width - len(rows[0]))
    header = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(head)]
    return header, [(n, tuple(r[:width]) + (None,) * (width - len(r))) for n, r in body]


def read_sheet(path: Path, sheet: str | None = None, header_row: int = 1) -> pd.DataFrame:
    header, body = _read(path, sheet, header_row)
    return pd.DataFrame([r for _, r in body], columns=header) if header else pd.DataFrame()


def read_sheet_with_rows(path: Path, sheet: str | None = None, header_row: int = 1) -> tuple[pd.DataFrame, dict]:
    """Like read_sheet plus a `_row` column (Excel row number) and {header: column letter} – for evidence."""
    header, body = _read(path, sheet, header_row)
    if not header:
        return pd.DataFrame(), {}
    df = pd.DataFrame([r for _, r in body], columns=header)
    df["_row"] = [n for n, _ in body]
    return df, {h: get_column_letter(i + 1) for i, h in enumerate(header) if not h.startswith("col")}


def to_num(s: pd.Series) -> pd.Series:
    cleaned = s.map(lambda v: v.replace(",", "") if isinstance(v, str) else v)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0).astype(float)

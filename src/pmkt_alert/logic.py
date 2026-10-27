"""Load and version the team's Alert_Logic workbook. Parameters are found by the
label text in Config column B (within its A–E section), never by cell position."""
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import openpyxl

PARAM_LABELS: dict[str, tuple[str, str]] = {
    "gmv_pace_low": ("A", "GMV pace thấp nếu <"),
    "spend_pace_low": ("A", "Spend pace thấp nếu <"),
    "spend_pace_high": ("A", "Spend pace quá cao nếu >"),
    "tacos_over": ("A", "TACoS vượt target nếu"),
    "not_running": ("A", '"Không chạy" nếu Spend pace <'),
    "budget_cap": ("A", "Ngưỡng cạn budget"),
    "trend_spend": ("B", "Spend"),
    "trend_acos": ("B", "ACoS"),
    "trend_tacos": ("B", "TACoS"),
    "trend_min_spend": ("B", "Sàn L7D Spend của PL"),
    "camp_cut": ("C", "CUT/OPTIMIZE nếu ACoS camp"),
    "camp_good": ("C", "MAINTAIN/PUSH hoặc SCALE UP nếu"),
    "camp_optimize": ("C", "OPTIMIZE nếu ACoS camp"),
    "min_clicks": ("C", "Sàn click tối thiểu"),
    "excess_high": ("C", "Excess spend để lên HIGH"),
    "action_window": ("D", 'Cửa sổ "đã action gần đây"'),
    "followup_days": ("D", "Hạn follow-up"),
    "improving_ratio": ("D", 'Coi là "đang cải thiện"'),
}
# Section B labels are bare metric names, so they must match exactly.
_EXACT = {"trend_spend", "trend_acos", "trend_tacos"}


class LogicError(Exception):
    pass


@dataclass
class Logic:
    path: Path
    version: int
    params: dict[str, float]
    k_by_type: dict[str, float]
    matrix: dict[str, tuple[str, str]]
    tiers_text: str


def version_from_name(name: str) -> int:
    m = re.search(r"Ver\s*(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else 1


def _key_for(section: str, label: str) -> str | None:
    for key, (sec, prefix) in PARAM_LABELS.items():
        if sec == section and (label == prefix if key in _EXACT else label.startswith(prefix)):
            return key
    return None


def _scan_config(ws):
    """Yield (row_index, kind, key, value): kind 'param' or 'k'."""
    section = None
    for row in ws.iter_rows(min_col=2, max_col=3):
        label_cell, value_cell = row[0], row[1]
        label = str(label_cell.value).strip() if label_cell.value is not None else ""
        if not label:
            continue
        m = re.match(r"^([A-E])\.\s", label)
        if m:
            section = m.group(1)
            continue
        if section == "E":
            yield label_cell.row, "k", label, value_cell.value
        elif section:
            key = _key_for(section, label)
            if key:
                yield label_cell.row, "param", key, value_cell.value


def load_logic(path: Path) -> Logic:
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        params, k_by_type = {}, {}
        for _, kind, key, value in _scan_config(wb["Config"]):
            (params if kind == "param" else k_by_type)[key] = float(value)
        missing = [k for k in PARAM_LABELS if k not in params]
        if missing:
            raise LogicError("Thiếu tham số: " + ", ".join(missing))
        matrix = {}
        for row in wb["Matrix_PL"].iter_rows(min_row=5, values_only=True):
            if row and isinstance(row[0], str) and re.fullmatch(r"[UFD]\|[UFD]\|[UFD]", row[0]):
                matrix[row[0]] = (row[5] or "", row[6] or "")
        tiers = []
        if "Logic_Tiers" in wb.sheetnames:
            for row in wb["Logic_Tiers"].iter_rows(values_only=True):
                cells = [str(v) for v in row if v not in (None, "")]
                if cells:
                    tiers.append(" | ".join(cells))
    finally:
        wb.close()
    return Logic(path, version_from_name(path.name), params, k_by_type, matrix, "\n".join(tiers))


def write_logic_version(logic: Logic, changes: dict[str, float | str], note: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = [version_from_name(p.name) for p in out_dir.glob("*.xlsx")]
    n = max([logic.version, *existing]) + 1  # never reuse a number, even after switching back to an old version
    out = out_dir / f"Alert_Logic_Ver {n}.xlsx"
    if out.exists():
        raise ValueError(f"{out.name} đã tồn tại")
    shutil.copyfile(logic.path, out)
    wb = openpyxl.load_workbook(out)
    params = {k: v for k, v in changes.items() if not k.startswith("matrix:")}
    rows = {key: r for r, kind, key, _ in _scan_config(wb["Config"]) if kind == "param"}
    for key, value in params.items():
        wb["Config"].cell(row=rows[key], column=3, value=value)
    for key, label in changes.items():
        if key.startswith("matrix:"):
            mkey = key.split(":", 1)[1]
            for row in wb["Matrix_PL"].iter_rows(min_row=5):
                if row[0].value == mkey:
                    row[5].value = label or None
    if "README_Flow" not in wb.sheetnames:
        wb.create_sheet("README_Flow")
    wb["README_Flow"].append(["", f"Ver {n} – {date.today():%d/%m/%Y}", note])
    wb.save(out)
    return out


def valid_change(key: str, value, logic: Logic) -> bool:
    if key in PARAM_LABELS:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return key.startswith("matrix:") and key[7:] in logic.matrix and isinstance(value, str)

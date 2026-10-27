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


# ---------------------------------------------------------------- Alert_Logic
CONFIG_ROWS = [  # (section header or None, label, value) in the order of the real workbook
    ("A", "A. PL – pacing so với target tháng", None),
    (None, "GMV pace thấp nếu < (%GMV ÷ time gone)", 0.85),
    (None, "Spend pace thấp nếu <", 0.9),
    (None, "Spend pace quá cao nếu >", 1.15),
    (None, "TACoS vượt target nếu (Actual ÷ Target) >", 1.1),
    (None, '"Không chạy" nếu Spend pace <', 0.1),
    (None, "Ngưỡng cạn budget (%Spend ≥)", 1),
    (None, None, None),
    ("B", "B. PL – trend L7D so với P7D (ngưỡng thay đổi ±)", None),
    (None, "Spend", 0.2),
    (None, "ACoS", 0.2),
    (None, "TACoS", 0.2),
    (None, "Sàn L7D Spend của PL để xét trend ($)", 50),
    ("C", "C. Campaign – dựa trên L7D", None),
    (None, "CUT/OPTIMIZE nếu ACoS camp ÷ ACoS PL >", 1.15),
    (None, "MAINTAIN/PUSH hoặc SCALE UP nếu ACoS camp ÷ ACoS PL ≤", 1),
    (None, "OPTIMIZE nếu ACoS camp ÷ ACoS PL >", 1.3),
    (None, "Sàn click tối thiểu (L7D)", 15),
    (None, "Excess spend để lên HIGH ($, trong L7D)", 30),
    (None, None, None),
    ("D", "D. Action log của PIC", None),
    (None, 'Cửa sổ "đã action gần đây" (ngày, tính cả as-of)', 3),
    (None, "Hạn follow-up = ngày action + (ngày)", 3),
    (None, 'Coi là "đang cải thiện" nếu ACoS L3D ≤ ACoS L7D ×', 0.9),
    (None, None, None),
    ("E", "E. k = số order kỳ vọng trước khi kết luận (theo loại campaign)", None),
    (None, "SPS_PRODUCTS", 3),
    (None, "SPS_BRANDS", 3),
    (None, "SPS_DISPLAY", 5),
]
_DROP_LABEL = {"min_clicks": "Sàn click tối thiểu (L7D)"}

MATRIX_LABELS = {
    **{k: "REVIEW ADS" for k in ["U|U|U", "U|U|F", "U|U|D", "U|F|U", "F|U|F", "F|U|D", "D|U|F", "D|U|D"]},
    **{k: "REVIEW SKU" for k in ["U|D|U", "F|U|U", "F|F|U", "F|D|U", "D|U|U", "D|F|U", "D|D|U"]},
    **{k: "SCALE" for k in ["U|F|D", "U|D|F", "U|D|D", "F|D|D", "D|D|D"]},
}


def make_logic(path: Path, insert_blank_rows_at: int | None = None, drop: str | None = None) -> Path:
    config = [[None, "CONFIG – mọi tham số alert", None],
              [None, "As-of date (ngày data hoàn chỉnh gần nhất)", None],
              [None, "Đầu tháng", None], [None, "Số ngày trong tháng", 31], [None, "Time gone", 0.6],
              [None, "L7D (7 ngày gần nhất)", "x"], [None, "P7D (7 ngày liền trước, để so sánh)", "x"]]
    for _, label, value in CONFIG_ROWS:
        if drop and label == _DROP_LABEL.get(drop):
            continue
        config.append([None, label, value])
    if insert_blank_rows_at:
        config[insert_blank_rows_at:insert_blank_rows_at] = [[None, None, None]] * 3
    matrix = [["MA TRẬN"], [None], [None], ["Key (Spend|ACoS|TACoS)", "Spend", "ACoS", "TACoS", "Tín hiệu", "Label", "Hành động gợi ý"]]
    for s in "UFD":
        for a in "UFD":
            for t in "UFD":
                key = f"{s}|{a}|{t}"
                label = MATRIX_LABELS.get(key)
                matrix.append([key, s, a, t, key, label, f"Gợi ý {key}" if label else None])
    return write_xlsx(path, {
        "README_Flow": [[None, "README", None], [None, "Luồng:", "demo"]],
        "Logic_Tiers": [["HỆ THỐNG LOGIC ALERT"], ["Tầng 1: pacing"]],
        "Config": config,
        "Matrix_PL": matrix,
    })

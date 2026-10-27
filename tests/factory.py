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


# ---------------------------------------------------------------- full input set
from datetime import date, datetime, timedelta  # noqa: E402

DAYS = [date(2026, 9, 20) + timedelta(days=i) for i in range(30)]  # 20/09 .. 19/10
PRODUCTS = [  # asin, sku, pl, pic
    ("B000000001", "S001", "PL Alpha", "PIC A"),
    ("B000000002", "S002", "PL Alpha", "PIC A"),
    ("B000000003", "S003", "PL Beta", "PIC A"),
    ("B000000004", "S004", "PL Beta", "PIC A"),
    ("B000000005", "S005", "PL Gamma", "PIC B"),
    ("B000000006", "S006", "PL Delta", 0),  # no PIC
]
FACTORY_DAILY_GMV = {"PL Alpha": 200.0, "PL Beta": 200.0}
FACTORY_DAILY_SPEND = {"PL Alpha": 12.0, "PL Beta": 12.0}
FACTORY_SPLIT_CAMPAIGN_ID = "100000000000002"
CAMPAIGNS = [  # id, name, type, asins, daily spend, clicks, sales, orders (per asin row)
    ("100000000000001", "Camp Alpha_SP_1790000001", "SPS_PRODUCTS", ["B000000001"], 5, 10, 30, 1),
    (FACTORY_SPLIT_CAMPAIGN_ID, "Camp Split_SP", "SPS_PRODUCTS", ["B000000002", "B000000003"], 4, 8, 10, 0),
    ("100000000000003", "Camp Gamma_SD", "SPS_DISPLAY", ["B000000005"], 6, 12, 20, 1),
    ("100000000000004", "Camp Orphan_SP", "SPS_PRODUCTS", ["B000000099"], 2, 4, 0, 0),
]
FACTORY_MAIN_ROWS = len(DAYS) * sum(len(c[3]) for c in CAMPAIGNS)
FACTORY_LOG_CAMPAIGNS = 3


def _raw_rows():
    head = ["report_date", "asin", "sku", "product_name", "ordered_gmv_usd", "ppc_ordered_gmv_usd",
            "ppc_clicks", "ppc_orders", "sp_spend", "sb_spend", "sd_spend", "DSP_Spend", "ordered_units"]
    rows = [head]
    for d in DAYS:
        for asin, sku, pl, _ in PRODUCTS:
            sp = 10 if (pl == "PL Gamma" and d >= date(2026, 10, 13)) else 1
            rows.append([datetime.combine(d, datetime.min.time()), asin, sku, f"Product {sku}", 100, 40, 20, 2, sp, 2, 3, 100, 3])
    return rows


def make_tracker(path: Path) -> Path:
    info = [["sku", "asin", "product_line_old", "status", "PMKT PIC_Final", "PIC Oct"],
            ["S001", "B000000001", "PL Old", "Inactive", "PIC B", "PIC B"]]  # duplicate asin, Active wins
    info += [[sku, asin, pl, "Active", pic, pic] for asin, sku, pl, pic in PRODUCTS]
    kpi = [["Month", "PIC SEM", "ASIN", "sku", "Product Line (Old)", "GMV", "Spend_final", "TACOS", "PIC"]]
    for month in (9, 10):
        for asin, sku, pl, pic in PRODUCTS:
            if pl in ("PL Alpha", "PL Beta"):
                kpi.append([month, 0, asin, sku, pl, 5000 if pl == "PL Alpha" else 3000, 300 if pl == "PL Alpha" else 100, 0.06, pic])
    summary = [["Date", None, None, "Campaign Gone"],
               ["Month", 10, None, "OCT_2026", "BAU", None, "FALL PRIME"],
               ["Timegone"],
               [None, None, None, "Day"] + [datetime(2026, 10, d) for d in range(1, 6)]]
    return write_xlsx(path, {
        "Summary": summary,
        "raw_sso_us": _raw_rows(),
        "Product Info": info,
        "KPI": kpi,
        "INELIGIBLE ASIN": [["log_date", "country", "sku", "account_name", "asin", "asin_status", "ad_group_name",
                             "lifecycle", "delivery_status", "delivery_reasons"],
                            [datetime(2026, 10, 18), "USA", "S003", "Main Account", "B000000003", None, "g", "Normal",
                             "INELIGIBLE", "CP_INELIGIBLE_ASIN"]],
    })


def make_ads(path: Path) -> Path:
    rows = [["report_date", "country", "account_name", "campaign_type", "campaign_id", "campaign_name", "asin",
             "spend_usd", "clicks", "impressions", "sales_14d", "unitsold_14d", "order_14d"]]
    for d in DAYS:
        for cid, name, typ, asins, spend, clicks, sales, orders in CAMPAIGNS:
            for asin in asins:
                rows.append([datetime.combine(d, datetime.min.time()), "USA", "Main Account", typ, cid, name, asin,
                             f"{spend:.10f}", f"{clicks:.10f}", "0E-10", f"{sales:.10f}", "0E-10", f"{orders:.10f}"])
    rows.append([datetime(2026, 10, 19), "USA", "Other Brand", "SPS_PRODUCTS", "900000000000001", "Other", "B000000001", "9", "1", "1", "1", "1", "1"])
    rows.append([datetime(2026, 10, 19), "USA", "DSP_Other", "DSP", "900000000000002", "Dsp", "B000000001", "9", "1", "1", "1", "1", "1"])
    return write_xlsx(path, {"ads_camp": rows})


def make_activity(path: Path) -> Path:
    head = ["ID", "Level", "Type", "Action", "From", "To", "Last Time Ineligible (UTC) ", "username"]
    rows = [head,
            ["1", "Campaign: Camp Alpha_SP_1790000001 | AdGroup: g | Target Keyword exact: k", "keywordTargetBid",
             "update", "$0.8", "$0.72", "Oct 18, 2026 10:00:00", "pica@example.com"],
            ["2", "Campaign: Camp Split_SP_Old", "campaignName", "update", "Camp Split_SP_Old", "Camp Split_SP",
             "Oct 10, 2026 09:00:00", "pica@example.com"],
            ["3", "Campaign: Camp Split_SP_Old", "campaignDailyBudget", "update", "$20", "$10",
             "Oct 09, 2026 09:00:00", "pica@example.com"],
            ["4", "Campaign: Camp Gamma_SD", "campaignStatus", "update", "Enabled", "Paused",
             "Oct 17, 2026 08:00:00", "picb@example.com"],
            ["5", "Portfolio: P1", "portfolioBudget", "update", "$1", "$2", "Oct 17, 2026 08:00:00", ""]]
    p = write_xlsx(path, {"Activity Log": rows})
    break_dimension(p)
    return p


def make_defind(path: Path) -> Path:
    return write_xlsx(path, {"Sheet1": [[None, "Tên File", "Data", "Sheet", "Meaning"],
                                        [1, "Tracking", "Raw data", "raw_sso_us", "Daily performance"]]})


def make_all(dir_: Path, names: dict[str, str] | None = None) -> dict[str, Path]:
    names = {"tracker": "tracker.xlsx", "ads": "ads.xlsx", "activity": "activity.xlsx",
             "logic": "Alert_Logic_Ver 1.xlsx", "defind": "defind.xlsx", **(names or {})}
    d = Path(dir_)
    return {"tracker": make_tracker(d / names["tracker"]), "ads": make_ads(d / names["ads"]),
            "activity": make_activity(d / names["activity"]), "logic": make_logic(d / names["logic"]),
            "defind": make_defind(d / names["defind"])}


def make_logic_v3(path: Path, blank: str | None = None, bad_matrix: bool = False) -> Path:
    """Mimics the team's v3 layout: re-lettered sections, 'Giá trị' header values, a scoring model
    instead of the 4 pacing thresholds, extra parameters the app does not use."""
    rows = [[None, "CONFIG – mọi tham số", None], [None, "As-of date", None], [None, "Time gone", 0.6],
            [None, "A. Phạm vi", None], [None, "Nhãn team được tracking", "Team X"],
            [None, "B. Trọng số các yếu tố", "Giá trị"], [None, "w1 – TACoS vs target", 3], [None, "w2 – Department", 3],
            [None, "D. Mốc điểm → action code", "Giá trị"], [None, "SCALE DOWN nếu điểm ≥", 50],
            [None, "E. Chốt chặn & luật cứng", "Giá trị"], [None, '"Không chạy" nếu Spend pace <', 0.1],
            [None, "Ngưỡng cạn budget (%Spend ≥)", 1],
            [None, "F. Trend L7D vs P7D (ngưỡng thay đổi ±)", "Giá trị"], [None, "Spend", 0.2], [None, "ACoS", 0.25],
            [None, "TACoS", 0.2], [None, "Sàn L7D Spend để xét trend ($)", 50],
            [None, "G. Campaign (L7D)", "Giá trị"], [None, "CUT/OPTIMIZE nếu ACoS camp ÷ ACoS PL >", 1.2],
            [None, "MAINTAIN/PUSH hoặc SCALE UP nếu ≤", 1], [None, "OPTIMIZE nếu ACoS camp ÷ ACoS PL >", 1.3],
            [None, "Sàn click tối thiểu (L7D)", 15], [None, "Excess spend để lên HIGH ($, L7D)", 30],
            [None, "H. Action log của PIC", "Giá trị"], [None, 'Cửa sổ "đã action gần đây" (ngày, gồm as-of)', 3],
            [None, "Hạn follow-up = ngày action + (ngày)", 3], [None, '"Đang cải thiện" nếu ACoS L3D ≤ ACoS L7D ×', 0.9],
            [None, "I. k = số order kỳ vọng (theo loại campaign)", "Giá trị"], [None, "SPS_PRODUCTS", 3],
            [None, "SPS_BRANDS", 3], [None, "SPS_DISPLAY", 5],
            [None, "J. Department (tự tính, không sửa)", "Giá trị"], [None, "Target GMV Dept", 1000]]
    if blank:
        for r in rows:
            if r[1] and str(r[1]).startswith(blank):
                r[2] = None
    matrix = [["MA TRẬN"], [None], [None], ["Key (Spend|ACoS|TACoS)", "Spend", "ACoS", "TACoS", "Tín hiệu", "Label", "Hành động gợi ý"]]
    for s in "UFD":
        for a in "UFD":
            for t in "UFD":
                key = f"{s}|{a}|{t}"
                label = MATRIX_LABELS.get(key)
                if bad_matrix and key == "U|U|U":
                    label = "REVIEW AD"  # typo
                matrix.append([key, s, a, t, key, label, f"Gợi ý {key}" if label else None])
    return write_xlsx(path, {"README_Flow": [[None, "README", None]], "Logic_Tiers": [["Mô hình chấm điểm v3"]],
                             "Config": rows, "Matrix_PL": matrix})

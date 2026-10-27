"""Detect the 5 input workbooks by content and load them into normalized frames."""
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd

from .xlsx import read_sheet, sheet_names, to_num

ROLES = ("tracker", "ads", "activity", "logic", "defind")
ROLE_HINT = {
    "tracker": "file Tracking: cần sheet raw_sso_us, Product Info, KPI",
    "ads": "file Ads by Campaign: cần sheet ads_camp",
    "activity": "file Activity Log: cần cột Level, username",
    "logic": "file Alert_Logic: cần sheet Config, Matrix_PL",
    "defind": "file Defind: cần cột Tên File",
}
BLANK = {"#N/A", "0", "0.0", "None", "nan"}


class InputError(Exception):
    pass


@dataclass
class Inputs:
    raw: pd.DataFrame
    products: pd.DataFrame
    kpi: pd.DataFrame
    ineligible: pd.DataFrame
    ads: pd.DataFrame
    activity: pd.DataFrame
    event_days: dict[date, str] = field(default_factory=dict)
    defind_text: str = ""


def _first_row(path: Path) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        ws = wb.worksheets[0]
        ws.reset_dimensions()
        row = next(ws.iter_rows(max_row=1, values_only=True), ())
    finally:
        wb.close()
    return [str(v).strip() for v in row if v is not None]


def _role_of(path: Path) -> str | None:
    sheets = set(sheet_names(path))
    if {"raw_sso_us", "Product Info", "KPI"} <= sheets:
        return "tracker"
    if "ads_camp" in sheets:
        return "ads"
    if {"Config", "Matrix_PL"} <= sheets:
        return "logic"
    head = _first_row(path)
    if "Level" in head and "username" in head:
        return "activity"
    if "Tên File" in head:
        return "defind"
    return None


def detect_inputs(paths: list[Path]) -> dict[str, Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.xlsx")) if p.is_dir() else [p]
    found: dict[str, list[Path]] = {}
    for f in files:
        if f.name.startswith("~$"):
            continue
        try:
            role = _role_of(f)
        except Exception:
            continue
        if role:
            found.setdefault(role, []).append(f)
    for role in ROLES:
        if role not in found:
            raise InputError(f"Thiếu {ROLE_HINT[role]}")
        if len(found[role]) > 1:
            raise InputError(f"Có nhiều hơn một {ROLE_HINT[role].split(':')[0]}: " + ", ".join(f.name for f in found[role]))
    return {role: found[role][0] for role in ROLES}


def _to_date(s: pd.Series) -> pd.Series:
    def one(v):
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, (int, float)) and not pd.isna(v):
            return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).date()
        t = pd.to_datetime(v, errors="coerce")
        return None if pd.isna(t) else t.date()
    return s.map(one)


def _clean_text(s: pd.Series) -> pd.Series:
    return s.map(lambda v: "" if v is None or str(v).strip() in BLANK else str(v).strip())


def _need(df: pd.DataFrame, cols: list[str], where: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise InputError(f"{where} thiếu cột: {', '.join(missing)}")


def _event_days(path: Path) -> dict[date, str]:
    if "Summary" not in sheet_names(path):
        return {}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Summary"]
        ws.reset_dimensions()
        rows = list(ws.iter_rows(min_row=1, max_row=4, values_only=True))
    finally:
        wb.close()
    if len(rows) < 4:
        return {}
    labels, days = rows[1], rows[3]
    out, current = {}, None
    for i in range(4, len(days)):
        lab = labels[i] if i < len(labels) else None
        current = lab if lab not in (None, "") else current
        d = days[i]
        if isinstance(d, (datetime, date)) and current:
            out[d.date() if isinstance(d, datetime) else d] = str(current)
    return out


def load_inputs(roles: dict[str, Path]) -> Inputs:
    t = roles["tracker"]
    raw = read_sheet(t, "raw_sso_us")
    _need(raw, ["report_date", "asin", "sku", "ordered_gmv_usd", "ppc_ordered_gmv_usd", "sp_spend", "sb_spend",
                "sd_spend", "ppc_clicks", "ppc_orders"], "raw_sso_us")
    raw = pd.DataFrame({
        "date": _to_date(raw["report_date"]), "asin": raw["asin"].astype(str), "sku": raw["sku"].astype(str),
        "gmv": to_num(raw["ordered_gmv_usd"]), "ads_gmv": to_num(raw["ppc_ordered_gmv_usd"]),
        "spend": to_num(raw["sp_spend"]) + to_num(raw["sb_spend"]) + to_num(raw["sd_spend"]),
        "clicks": to_num(raw["ppc_clicks"]), "orders": to_num(raw["ppc_orders"]),
    }).dropna(subset=["date"])

    info = read_sheet(t, "Product Info")
    _need(info, ["asin", "sku", "product_line_old", "status"], "Product Info")
    pic_cols = [c for c in info.columns if c.startswith("PIC ") or c == "PMKT PIC_Final"]
    products = pd.DataFrame({"asin": info["asin"].astype(str), "sku": info["sku"].astype(str),
                             "pl": _clean_text(info["product_line_old"]), "status": _clean_text(info["status"])})
    for c in pic_cols:
        products[c] = _clean_text(info[c])

    k = read_sheet(t, "KPI")
    _need(k, ["Month", "ASIN", "GMV", "Spend_final"], "KPI")
    kpi = pd.DataFrame({"month": to_num(k["Month"]).astype(int), "asin": k["ASIN"].astype(str),
                        "gmv": to_num(k["GMV"]), "spend": to_num(k["Spend_final"])})

    if "INELIGIBLE ASIN" in sheet_names(t):
        ie = read_sheet(t, "INELIGIBLE ASIN")
        ineligible = pd.DataFrame({"date": _to_date(ie.get("log_date", pd.Series(dtype=object))),
                                   "asin": ie.get("asin", pd.Series(dtype=object)).astype(str),
                                   "status": ie.get("delivery_status", pd.Series(dtype=object)),
                                   "reason": ie.get("delivery_reasons", pd.Series(dtype=object))})
    else:
        ineligible = pd.DataFrame(columns=["date", "asin", "status", "reason"])

    a = read_sheet(roles["ads"], "ads_camp")
    _need(a, ["report_date", "account_name", "campaign_type", "campaign_id", "campaign_name", "asin",
              "spend_usd", "clicks", "sales_14d", "order_14d"], "ads_camp")
    a = a[a["account_name"].astype(str).str.strip() == "Yes4All"]
    ads = pd.DataFrame({
        "date": _to_date(a["report_date"]), "type": a["campaign_type"].astype(str),
        "campaign_id": a["campaign_id"].map(lambda v: str(int(v)) if isinstance(v, (int, float)) else str(v).strip()),
        "campaign": a["campaign_name"].astype(str), "asin": a["asin"].astype(str),
        "spend": to_num(a["spend_usd"]), "clicks": to_num(a["clicks"]),
        "sales": to_num(a["sales_14d"]), "orders": to_num(a["order_14d"]),
    }).dropna(subset=["date"]).reset_index(drop=True)

    log = read_sheet(roles["activity"])
    cols = ["id", "level", "type", "action", "from_", "to", "time", "user"]
    if log.empty:
        activity = pd.DataFrame(columns=cols)
    else:
        activity = log.iloc[:, :8].copy()
        activity.columns = cols[: activity.shape[1]]
        activity = activity.reindex(columns=cols)

    d = read_sheet(roles["defind"])
    defind_text = "\n".join(" | ".join(str(v) for v in row if v not in (None, "") and not pd.isna(v))
                            for row in [list(d.columns)] + d.values.tolist())
    defind_text = defind_text.replace("col0 | ", "")

    return Inputs(raw, products, kpi, ineligible, ads, activity, _event_days(t), defind_text)

"""Tier 2B – inventory guard (logic v4, Config K). Stock never changes the score; it only blocks advice that can't or
shouldn't be followed: SCALE UP while the PL's sellers run out, pushing campaigns whose spend sits on out-of-stock ASINs.
Stock = Inventory AMZ (latest log_date ≤ as-of); units sold = raw ordered_units (negatives dropped); incoming stock has
no source yet (0). Missing stock for an ASIN → unknown (not guarded); stale stock → whole guard skipped, tier 0 warns."""
from datetime import date, timedelta

import pandas as pd

from . import CAMP_SCALE_UP, PUSH

OUT, LOW, NORMAL, EXCESS = "HẾT HÀNG", "SẮP HẾT", "BÌNH THƯỜNG", "DƯ HÀNG"
L_OK, L_ATTN, L_CRIT, L_EXCESS = "THOẢI MÁI", "CẦN CHÚ Ý", "NGHIÊM TRỌNG", "DƯ HÀNG"
WAIT_STOCK = "CHỜ HÀNG"
CAMP_PAUSE_OOS, CAMP_HOLD_LOW = "PAUSE – HẾT HÀNG", "GIỮ – SẮP HẾT"
CHECK_STOCK = "Kiểm tra tồn kho trước"


def sku_cover(inventory: pd.DataFrame, raw: pd.DataFrame, asins: list[str], as_of: date, p: dict) -> tuple[pd.DataFrame, dict]:
    """Per ASIN: stock, average units/day over the sales window, days of stock left and status."""
    inv = inventory[inventory["date"] <= as_of] if len(inventory) else inventory
    latest = inv.sort_values("date").groupby("asin").tail(1).set_index("asin") if len(inv) else pd.DataFrame()
    newest = max(inv["date"]) if len(inv) else None
    n = int(p["inv_sales_days"])
    window = raw[(raw["date"] > as_of - timedelta(days=n)) & (raw["date"] <= as_of)]
    units = window.assign(units=window["units"].clip(lower=0)).groupby("asin")["units"].sum() / n if len(window) else pd.Series(dtype=float)
    rows = []
    for a in asins:
        stock = float(latest.at[a, "stock"]) if a in latest.index else None
        avg = float(units.get(a, 0.0))
        if stock is None:
            status, days = None, None
        elif stock <= 0:  # incoming within inv_incoming_days: no source yet
            status, days = OUT, 0.0
        elif avg <= 0:
            status, days = NORMAL, None  # nothing sold in the window: not judged
        else:
            days = stock / avg
            status = LOW if days < p["inv_low_days"] else EXCESS if days > p["inv_high_days"] else NORMAL
        rows.append({"asin": a, "stock": stock, "stock_date": latest.at[a, "date"] if a in latest.index else None,
                     "avg_units": avg, "days_left": days, "inv_status": status})
    stale = newest is None or (as_of - newest).days > p["inv_stale_days"]
    missing = sorted(a for a in asins if a not in latest.index)
    df = pd.DataFrame(rows, columns=["asin", "stock", "stock_date", "avg_units", "days_left", "inv_status"])
    df["inv_status"] = df["inv_status"].astype(object).where(df["inv_status"].notna(), None)  # unknown stays None
    return df, {"missing": missing, "stale": stale, "latest": newest}


def pl_inventory(pl: pd.DataFrame, cover: pd.DataFrame, raw: pd.DataFrame, amap: pd.DataFrame, as_of: date, p: dict) -> pd.DataFrame:
    """PL level from the share of L7D GMV on out / low-stock ASINs (weighted by sales, so best sellers count more)."""
    l7d = raw[(raw["date"] > as_of - timedelta(days=7)) & (raw["date"] <= as_of)]
    g = l7d.groupby("asin")["gmv"].sum().rename("gmv").reset_index().merge(amap[["asin", "pl"]], on="asin")
    g = g.merge(cover[["asin", "inv_status"]], on="asin", how="left")
    total = g.groupby("pl")["gmv"].sum()
    low = g[g["inv_status"].isin([OUT, LOW])].groupby("pl")["gmv"].sum()
    exc = g[g["inv_status"] == EXCESS].groupby("pl")["gmv"].sum()
    out = pl.copy()
    out["inv_low_share"] = [float(low.get(x, 0.0)) / total[x] if total.get(x, 0) else 0.0 for x in out["pl"]]
    out["inv_excess_share"] = [float(exc.get(x, 0.0)) / total[x] if total.get(x, 0) else 0.0 for x in out["pl"]]
    out["inv_level"] = [L_CRIT if lo >= p["inv_critical"] else L_ATTN if lo >= p["inv_attention"] else
                        L_EXCESS if ex >= p["inv_excess"] else L_OK
                        for lo, ex in zip(out["inv_low_share"], out["inv_excess_share"])]
    return out


def guard_pl(pl: pd.DataFrame) -> pd.DataFrame:
    out = pl.copy()
    actions, sevs, reasons, trends = [], [], [], []
    for r in out.to_dict("records"):
        act, sev, reason, lv = r["pacing_action"], r["pacing_sev"], r.get("pacing_reason") or "", r.get("inv_level")
        share = r.get("inv_low_share")
        short = lv in (L_ATTN, L_CRIT)
        if short and str(act).startswith("SCALE UP"):
            act = WAIT_STOCK
            sev = "MED" if lv == L_CRIT else "LOW"
            reason += f" | Tồn kho {lv}" + (f": {share:.0%} GMV L7D từ SKU hết/sắp hết" if share is not None else "") + " – chưa tăng chi"
        if lv == L_CRIT:
            sev = sev if sev in ("HIGH", "MED") else "MED"
            reason += " | Tồn kho NGHIÊM TRỌNG – kiểm tra kế hoạch nhập hàng"
        elif lv == L_EXCESS:
            reason += " | Phần lớn GMV từ SKU dư tồn – ưu tiên giữ/tối ưu camp của SKU dư, cắt ở SKU khác"
        trend = r.get("trend_action") or ""
        if short and r.get("trend_label") in ("REVIEW ADS", "REVIEW SKU"):
            trend = f"{trend} · {CHECK_STOCK}" if trend else CHECK_STOCK
        actions.append(act), sevs.append(sev), reasons.append(reason.lstrip(" |")), trends.append(trend)
    out["pacing_action"], out["pacing_sev"], out["pacing_reason"], out["trend_action"] = actions, sevs, reasons, trends
    return out


def guard_camp(camp: pd.DataFrame, cover: pd.DataFrame, ads: pd.DataFrame, as_of: date, p: dict) -> pd.DataFrame:
    """≥ inv_camp_block of a campaign's L7D spend on out-of-stock ASINs → PAUSE (overrides everything); on out/low
    stock → no push (SCALE UP / PUSH become GIỮ – SẮP HẾT, cuts stay); on excess stock → a note only."""
    l7d = ads[(ads["date"] > as_of - timedelta(days=7)) & (ads["date"] <= as_of)]
    s = l7d.groupby(["campaign_id", "asin"])["spend"].sum().reset_index().merge(cover[["asin", "inv_status"]], on="asin", how="left")
    total = s.groupby("campaign_id")["spend"].sum()
    share = lambda st: (s[s["inv_status"].isin(st)].groupby("campaign_id")["spend"].sum() / total).fillna(0.0)  # noqa: E731
    out_s, low_s, exc_s = share([OUT]), share([OUT, LOW]), share([EXCESS])
    out = camp.copy()
    block = p["inv_camp_block"]
    acts, sevs, notes = [], [], []
    for r in out.to_dict("records"):
        cid, act, sev = r["campaign_id"], r["base_action"], r["sev"]
        note = ""
        if out_s.get(cid, 0.0) >= block:
            act, sev, note = CAMP_PAUSE_OOS, "HIGH", f"{out_s[cid]:.0%} spend L7D trên ASIN hết hàng"
        elif low_s.get(cid, 0.0) >= block:
            note = f"{low_s[cid]:.0%} spend L7D trên ASIN hết/sắp hết hàng"
            if act in (CAMP_SCALE_UP, PUSH):
                act, sev = CAMP_HOLD_LOW, ""
        if exc_s.get(cid, 0.0) >= block:
            note = f"{note} · SKU dư tồn" if note else "SKU dư tồn"
        acts.append(act), sevs.append(sev), notes.append(note)
    out["base_action"], out["sev"], out["inv_note"] = acts, sevs, notes
    return out

"""Performance Review (logic file sheet 'Performance Review_brief'): for a PIC / timeframe / product line –
summary tiles, PL and SKU target-vs-actual tables, daily chart series and the campaign list.
Actuals follow the timeframe; targets are the month's KPI (month of the timeframe's end). Daily targets spread the
monthly target with the Data workbook's Summary %Contribution (GMV & RS: GMV row; spend: PPC row), else evenly.
Scope and PIC as in the score model: Team Label = the logic's team label, PIC = PMKT PIC_Final."""
import calendar
from datetime import date, timedelta

import pandas as pd

from .aggregate import NO_PIC, asin_map

_div = lambda a, b: (a / b) if b and a is not None else None  # noqa: E731


def _iso(d) -> str:
    return d.isoformat() if d else None


def _ineligible(ie: pd.DataFrame, asin: str, month_start: date, end: date, last_log: date | None) -> dict:
    """current = the ASIN's delivery_status on the last log day ≤ end ('' = not listed = eligible);
    changes = status changes day to day this month; days = days listed as INELIGIBLE this month."""
    rows = ie[(ie["asin"] == asin) & (ie["date"] >= month_start) & (ie["date"] <= end)]
    by_day = {d: str(s).strip().upper() for d, s in zip(rows["date"], rows["status"]) if s == s and s is not None}
    flips, prev, day = 0, None, month_start
    while day <= end:
        state = by_day.get(day, "")
        if prev is not None and state != prev:
            flips += 1
        prev, day = state, day + timedelta(days=1)
    return {"current": by_day.get(last_log, "") if last_log else "", "changes": flips,
            "days": sum(1 for v in by_day.values() if v.startswith("INELIGIBLE"))}


LISTING_ISSUE_LIFECYCLE = ("withdrawal",)  # Normal / Introduction / Turnkey are ordinary stages


def _listing_issue(row: dict) -> str:
    parts = []
    status, life = str(row.get("status") or ""), str(row.get("lifecycle") or "")
    if status and status.lower() != "active":
        parts.append(status)
    if life.lower() in LISTING_ISSUE_LIFECYCLE:
        parts.append(life)
    return " · ".join(parts)


def performance(inputs, rj: dict, team_label: str = "", pic: str | None = None, pl: str | None = None,
                start: str | None = None, end: str | None = None) -> dict:
    """team_label scopes like the score model; with the Ver 1 rule model (no label) the month's PIC column is used."""
    as_of = date.fromisoformat(rj["as_of"])
    end_d = min(date.fromisoformat(end), as_of) if end else as_of
    month_start = end_d.replace(day=1)
    start_d = max(date.fromisoformat(start), month_start) if start else month_start
    dim = calendar.monthrange(end_d.year, end_d.month)[1]

    pic_col = "PMKT PIC_Final" if rj.get("model") == "score_v3" and "PMKT PIC_Final" in inputs.products.columns else None
    amap = asin_map(inputs.products, end_d, pic_col=pic_col) if pic_col else asin_map(inputs.products, end_d)
    if team_label and "team" in amap.columns:
        amap = amap[amap["team"] == team_label]
    pics = sorted(set(amap["pic"]) - {NO_PIC})
    pls_all = sorted(set(amap.loc[amap["pic"] == pic, "pl"]) if pic else set(amap["pl"]))
    if pic:
        amap = amap[amap["pic"] == pic]
    # Summary tiles + PL table: the PIC; SKU table, charts and campaigns follow the Product line filter (brief C7).
    raw = inputs.raw[(inputs.raw["date"] >= start_d) & (inputs.raw["date"] <= end_d) & inputs.raw["asin"].isin(set(amap["asin"]))]
    raw = raw.merge(amap[["asin", "pl"]], on="asin")
    kpi = inputs.kpi[(inputs.kpi["month"] == end_d.month) & inputs.kpi["asin"].isin(set(amap["asin"]))].merge(amap[["asin", "pl"]], on="asin")
    contrib = {d: v for d, v in (inputs.contrib or {}).items() if d.month == end_d.month and d.year == end_d.year}
    share = lambda d, k: contrib[d][k] if d in contrib else 1 / dim  # noqa: E731

    def totals(r: pd.DataFrame, k: pd.DataFrame) -> tuple[dict, dict, dict]:
        act = {"gmv": float(r["gmv"].sum()), "rs": float(r["units"].sum()), "spend": float(r["spend"].sum())}
        act["tacos"] = _div(act["spend"], act["gmv"])
        tgt = {"gmv": float(k["gmv"].sum()), "rs": float(k["rs"].sum()), "spend": float(k["spend"].sum())}
        tgt["tacos"] = _div(tgt["spend"], tgt["gmv"])
        ach = {m: _div(act[m], tgt[m]) for m in ("gmv", "rs", "spend", "tacos")}
        return tgt, act, ach

    tgt, act, _ = totals(raw, kpi)
    ads_gmv, units, ads_units = float(raw["ads_gmv"].sum()), float(raw["units"].sum()), float(raw["ads_units"].sum())
    summary = {
        "time_gone": end_d.day / dim,
        "campaign_gone": sum(v["gmv"] for d, v in contrib.items() if d <= end_d) if contrib else None,
        "gmv": act["gmv"], "gmv_target": tgt["gmv"], "gmv_pct": _div(act["gmv"], tgt["gmv"]),
        "spend": act["spend"], "spend_target": tgt["spend"], "spend_pct": _div(act["spend"], tgt["spend"]),
        "ads_nmv": ads_gmv, "acos": _div(act["spend"], ads_gmv), "tacos": act["tacos"],
        "ads_rs_share": _div(ads_units, units),
    }

    pl_rows = {r["pl"]: r for r in rj.get("pl", [])}
    pl_map = amap if not pl else amap[amap["pl"] == pl]
    pls = []
    for name in sorted(set(amap["pl"])):  # every PL of the PIC
        t, a, ach = totals(raw[raw["pl"] == name], kpi[kpi["pl"] == name])
        r = pl_rows.get(name, {})
        pls.append({"pl": name, "target": t, "actual": a, "achieve": ach, "action": r.get("pacing_action") or "",
                    "sev": r.get("pacing_sev") or "", "reason": r.get("pacing_reason") or ""})

    ie = inputs.ineligible
    logs = ie["date"].dropna() if len(ie) else pd.Series(dtype=object)
    logs = logs[logs <= end_d]
    last_log = max(logs) if len(logs) else None  # judged at the end date, not the newest log
    info = inputs.products.drop_duplicates("asin").set_index("asin")
    raw_pl, kpi_pl = raw[raw["pl"].isin(set(pl_map["pl"]))], kpi[kpi["pl"].isin(set(pl_map["pl"]))]
    stock = dict(zip(kpi["asin"], kpi["stock"])) if "stock" in kpi.columns else {}
    skus = []
    for a, sku, name in sorted(zip(pl_map["asin"], pl_map["sku"] if "sku" in pl_map.columns else pl_map["asin"], pl_map["pl"]),
                               key=lambda x: (x[2], x[1])):
        t, ac, ach = totals(raw[raw["asin"] == a], kpi[kpi["asin"] == a])
        prod = info.loc[a].to_dict() if a in info.index else {}
        st = stock.get(a)
        skus.append({"sku": sku, "asin": a, "pl": name, "product": prod.get("product_name") or "",
                     "ineligible": _ineligible(ie, a, month_start, end_d, last_log),
                     "stock": None if st is None or st != st else float(st), "listing_issue": _listing_issue(prod),
                     "target": t, "actual": ac, "achieve": ach})

    daily = []
    by_day = raw_pl.groupby("date")[["gmv", "spend", "ads_gmv", "units", "ads_units"]].sum()
    t_pl, _, _ = totals(raw_pl, kpi_pl)
    day = start_d
    while day <= end_d:
        v = by_day.loc[day] if day in by_day.index else None
        g, s, ag = (float(v["gmv"]), float(v["spend"]), float(v["ads_gmv"])) if v is not None else (0.0, 0.0, 0.0)
        u, au = (float(v["units"]), float(v["ads_units"])) if v is not None else (0.0, 0.0)
        gt, stg = t_pl["gmv"] * share(day, "gmv"), t_pl["spend"] * share(day, "ppc")
        daily.append({"date": day.isoformat(), "gmv": g, "gmv_target": gt, "ads_nmv": ag, "ads_rs_share": _div(au, u),
                      "spend": s, "spend_target": stg, "acos": _div(s, ag), "tacos": _div(s, g), "tacos_target": _div(stg, gt)})
        day += timedelta(days=1)

    ads = inputs.ads[(inputs.ads["date"] >= start_d) & (inputs.ads["date"] <= end_d) & inputs.ads["asin"].isin(set(pl_map["asin"]))]
    ads = ads.merge(pl_map[["asin", "pl"]], on="asin")
    g = ads.groupby(["campaign_id", "pl"]).agg(campaign=("campaign", "first"), spend=("spend", "sum"),
                                              nmv=("sales", "sum"), orders=("orders", "sum")).reset_index()
    run_camp = {(c.get("campaign_id"), c.get("pl")): c for c in rj.get("camp", [])}
    campaigns = []
    for r in g.sort_values("spend", ascending=False).to_dict("records"):
        c = run_camp.get((r["campaign_id"], r["pl"]), {})
        l7, p7 = c.get("l7d_acos"), c.get("p7d_acos")
        campaigns.append({"campaign": r["campaign"], "pl": r["pl"], "spend": r["spend"], "nmv": r["nmv"], "orders": r["orders"],
                          "acos": _div(r["spend"], r["nmv"]), "trend_spend": c.get("d_spend"),
                          "trend_acos": (l7 / p7 - 1) if l7 is not None and p7 else None,
                          "last_action": c.get("last_action_date"), "last_action_type": c.get("last_action_type") or "",
                          "alert": c.get("sev") in ("HIGH", "MED"), "action": c.get("final_label") or c.get("base_action") or ""})

    return {"filters": {"pic": pic, "pl": pl, "start": _iso(start_d), "end": _iso(end_d), "pics": pics, "pls": pls_all,
                        "min": _iso(month_start), "max": _iso(as_of)},
            "summary": summary, "pls": pls, "skus": skus, "daily": daily, "campaigns": campaigns}

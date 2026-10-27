"""PIC scorecard: each PIC measured against their own targets, scored 0–100 relative to the other PICs
(best = 100, worst = 0) per measure, then a weighted average. Plus weekly history from raw_sso_us."""
from datetime import date, timedelta

import pandas as pd

from .aggregate import NO_PIC, asin_map
from .rules import ACTIONED, OLD_ACTION, div
from .windows import Windows

METRICS = [  # key, label, higher_better (None = closer to 1 is better)
    {"key": "gmv_pace", "short": "GMV pace", "label": "Tiến độ GMV (÷ time gone)", "higher_better": True, "fmt": "x"},
    {"key": "spend_pace_gap", "short": "Lệch spend pace", "label": "Spend đúng tiến độ (lệch so với 1)", "higher_better": False, "fmt": "x"},
    {"key": "tacos_ratio", "short": "TACoS ÷ target", "label": "TACoS ÷ target", "higher_better": False, "fmt": "x"},
    {"key": "acos_l7d", "short": "ACoS L7D", "label": "ACoS L7D", "higher_better": False, "fmt": "%"},
    {"key": "excess_share", "short": "Excess / spend", "label": "Excess spend / spend L7D", "higher_better": False, "fmt": "%"},
    {"key": "action_rate", "short": "Action 7 ngày", "label": "Tỉ lệ camp alert được action trong 7 ngày", "higher_better": True, "fmt": "%"},
    {"key": "followup_success", "short": "Đang cải thiện", "label": "Tỉ lệ action đang cải thiện", "higher_better": True, "fmt": "%"},
]


def minmax_scores(values: dict, higher_better: bool) -> dict:
    nums = [v for v in values.values() if v is not None]
    if not nums:
        return {k: None for k in values}
    lo, hi = min(nums), max(nums)
    out = {}
    for k, v in values.items():
        if v is None:
            out[k] = None
        elif hi == lo:
            out[k] = 100.0
        else:
            s = (v - lo) / (hi - lo) * 100
            out[k] = round(s if higher_better else 100 - s, 1)
    return out


def _pic_values(rj: dict, pic: str, time_gone: float) -> dict:
    pls = [r for r in rj["pl"] if r["pic"] == pic]
    camps = [r for r in rj["camp"] if r["pic"] == pic]
    s = lambda rows, k: sum(r.get(k) or 0 for r in rows)  # noqa: E731
    tg, ts, gm, sm = s(pls, "target_gmv"), s(pls, "target_spend"), s(pls, "gmv_mtd"), s(pls, "spend_mtd")
    gmv_pct, spend_pct = div(gm, tg, None), div(sm, ts, None)
    tacos, target_tacos = div(sm, gm, None), div(ts, tg, None)
    alerted = [c for c in camps if c["sev"] in ("HIGH", "MED")]
    acted = [c for c in camps if c["status"] in (ACTIONED, OLD_ACTION)]
    digest = next((d for d in rj["digest"] if d["pic"] == pic), {})
    recent = (date.fromisoformat(rj["as_of"]) - timedelta(days=6)).isoformat()  # acted on within L7D
    camp_spend = s(pls, "camp_l7d_spend")
    return {
        "pl_count": len(pls), "target_gmv": tg, "gmv_mtd": gm, "target_spend": ts, "spend_mtd": sm,
        "gmv_pct": gmv_pct, "spend_pct": spend_pct,
        "gmv_pace": None if gmv_pct is None else gmv_pct / time_gone,
        "spend_pace": None if spend_pct is None else spend_pct / time_gone,
        "spend_pace_gap": None if spend_pct is None else abs(spend_pct / time_gone - 1),
        "tacos": tacos, "target_tacos": target_tacos,
        "tacos_ratio": None if tacos is None or not target_tacos else tacos / target_tacos,
        "acos_l7d": div(camp_spend, s(pls, "camp_l7d_sales"), None),
        "excess_new": digest.get("excess_new", 0.0), "excess_share": div(digest.get("excess_new", 0.0), camp_spend, None),
        "high_alerts": digest.get("pl_high", 0) + digest.get("camp_high", 0),
        "alerted_camps": len(alerted),
        "action_rate": div(sum(1 for c in alerted if c.get("last_action_date") and str(c["last_action_date"]) >= recent),
                           len(alerted), None),
        "followup_success": div(sum(1 for c in acted if str(c.get("followup_check", "")).startswith("Đang cải thiện")),
                                len(acted), None),
    }


def scorecard(rj: dict, weights: dict | None = None) -> dict:
    time_gone = Windows(date.fromisoformat(rj["as_of"])).time_gone
    pics = sorted({d["pic"] for d in rj["digest"]})
    values = {p: _pic_values(rj, p, time_gone) for p in pics}
    ranked = [p for p in pics if p != NO_PIC]
    weights = {m["key"]: 1.0 for m in METRICS} | (weights or {})
    scores = {p: {} for p in pics}
    for m in METRICS:
        sc = minmax_scores({p: values[p][m["key"]] for p in ranked}, m["higher_better"])
        for p in pics:
            scores[p][m["key"]] = sc.get(p)
    out = []
    for p in pics:
        parts = [(scores[p][k], w) for k, w in weights.items() if w and scores[p].get(k) is not None]
        total = round(sum(s * w for s, w in parts) / sum(w for _, w in parts), 1) if parts and p in ranked else None
        out.append({"pic": p, "values": values[p], "scores": scores[p], "total": total})
    order = sorted((x for x in out if x["total"] is not None), key=lambda x: -x["total"])
    for i, x in enumerate(order, 1):
        x["rank"] = i
    for x in out:
        x.setdefault("rank", None)
    out.sort(key=lambda x: (x["rank"] is None, x["rank"] or 0, x["pic"]))
    return {"as_of": rj["as_of"], "time_gone": time_gone, "metrics": METRICS, "weights": weights, "pics": out}


def weekly(inputs, as_of: date, weeks: int = 8) -> list[dict]:
    """Per PIC per ISO week (Mon–Sun) up to as_of: GMV, ads spend, ads GMV, TACoS, ACoS."""
    amap = asin_map(inputs.products, as_of)
    start = as_of - timedelta(days=as_of.weekday()) - timedelta(weeks=weeks - 1)
    raw = inputs.raw[(inputs.raw["date"] >= start) & (inputs.raw["date"] <= as_of)].merge(amap[["asin", "pic"]], on="asin")
    if raw.empty:
        return []
    raw = raw.assign(week=[d - timedelta(days=d.weekday()) for d in raw["date"]])
    g = raw.groupby(["pic", "week"])[["gmv", "spend", "ads_gmv"]].sum().reset_index()
    g["tacos"] = [div(s, v, None) for s, v in zip(g["spend"], g["gmv"])]
    g["acos"] = [div(s, v, None) for s, v in zip(g["spend"], g["ads_gmv"])]
    g["week"] = g["week"].map(lambda d: d.isoformat())
    g["days"] = [min(7, (as_of - date.fromisoformat(w)).days + 1) for w in g["week"]]
    return [{k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
            for r in g.to_dict("records")]

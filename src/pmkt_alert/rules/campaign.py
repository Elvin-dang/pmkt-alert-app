"""Tier 3 – (campaign, PL) actions (port of Campaign_Alert Q–AB).
A missing ratio mirrors Excel, where "" > number is TRUE and "" <= number is FALSE."""
import math

import pandas as pd

from . import (BETTER_ACOS, CAMP_SCALE_UP, CHECK_PLAN, CUT, MAINTAIN, OPTIMIZE, PAUSE, PUSH, WAIT, WATCH,
               WORSE_ACOS, WORSE_BOTH, div)


def _gt(x, thr) -> bool:
    return True if x is None else x > thr


def _le(x, thr) -> bool:
    return False if x is None else x <= thr


def _acos(spend, sales):
    return None if not sales else spend / sales


def _base_action(r, p) -> str:
    if not r.enough:
        return WAIT
    if r.l7d_orders == 0:
        return PAUSE
    act, ratio = r.pl_action, r.acos_ratio
    if act.startswith("NO PLAN"):
        return CHECK_PLAN
    if act.startswith(("SCALE DOWN", "OPTIMIZE", "BUDGET CAP")):
        if _gt(ratio, p["camp_cut"]):
            return CUT
        return PUSH if _le(ratio, p["camp_good"]) else WATCH
    if act.startswith("SCALE UP"):
        if _le(ratio, p["camp_good"]):
            return CAMP_SCALE_UP
        return OPTIMIZE if _gt(ratio, p["camp_optimize"]) else MAINTAIN
    return OPTIMIZE if _gt(ratio, p["camp_optimize"]) else MAINTAIN


def _trend(d_acos, d_spend, p) -> str:
    if d_acos is None:
        return ""
    if d_acos >= p["trend_acos"]:
        return WORSE_BOTH if d_spend is not None and d_spend >= p["trend_spend"] else WORSE_ACOS
    if d_acos <= -p["trend_acos"]:
        return BETTER_ACOS
    return ""


def _sev(r, p) -> str:
    a = r.base_action
    if a == WAIT:
        return ""
    if a == PAUSE or (a == CUT and r.excess >= p["excess_high"]):
        return "HIGH"
    if a in (CUT, OPTIMIZE, CAMP_SCALE_UP, CHECK_PLAN) or r.camp_trend.startswith("XẤU"):
        return "MED"
    return "LOW"


def _obj(values, index) -> pd.Series:
    return pd.Series(values, index=index, dtype=object)


def campaign(camp: pd.DataFrame, pl: pd.DataFrame, p: dict, k_by_type: dict) -> pd.DataFrame:
    base = pl[["pl", "pic", "pacing_action", "camp_l7d_spend", "camp_l7d_sales", "camp_l7d_clicks", "camp_l7d_orders"]]
    out = camp.merge(base, on="pl", how="left").rename(columns={"pacing_action": "pl_action"})
    out["pl_action"] = out["pl_action"].fillna("")
    out["pic"] = out["pic"].fillna("")
    out["unit_id"] = [f"camp:{c}:{p_}" for c, p_ in zip(out.campaign_id, out.pl)]
    out["pl_acos"] = [div(s, v) for s, v in zip(out.camp_l7d_spend.fillna(0), out.camp_l7d_sales.fillna(0))]
    out["pl_cr"] = [div(o, c) for o, c in zip(out.camp_l7d_orders.fillna(0), out.camp_l7d_clicks.fillna(0))]
    idx = out.index
    l7 = [_acos(s, v) for s, v in zip(out.l7d_spend, out.l7d_sales)]
    p7 = [_acos(s, v) for s, v in zip(out.p7d_spend, out.p7d_sales)]
    l3 = [_acos(s, v) for s, v in zip(out.l3d_spend, out.l3d_sales)]
    d_spend = [None if not ps else ls / ps - 1 for ls, ps in zip(out.l7d_spend, out.p7d_spend)]
    d_acos = [None if a is None or not b else a / b - 1 for a, b in zip(l7, p7)]  # P7D ACoS 0 → no trend (Excel IFERROR)
    ratio = [None if a is None or not b else a / b for a, b in zip(l7, out.pl_acos)]
    out["l7d_acos"], out["p7d_acos"], out["l3d_acos"] = _obj(l7, idx), _obj(p7, idx), _obj(l3, idx)
    out["d_spend"], out["d_acos"], out["acos_ratio"] = _obj(d_spend, idx), _obj(d_acos, idx), _obj(ratio, idx)
    floor = p["min_clicks"]
    default_k = k_by_type.get("SPS_PRODUCTS", 3)
    out["min_clicks"] = [int(floor) if not cr else int(max(floor, math.ceil(round(k_by_type.get(t, default_k) / cr, 9))))
                         for t, cr in zip(out.type, out.pl_cr)]
    out["enough"] = out.l7d_clicks >= out.min_clicks
    out["excess"] = [max(0.0, s - v * a) for s, v, a in zip(out.l7d_spend, out.l7d_sales, out.pl_acos)]
    out["camp_trend"] = [_trend(a, s, p) for a, s in zip(d_acos, d_spend)]
    out["base_action"] = [_base_action(r, p) for r in out.itertuples()]
    out["sev"] = [_sev(r, p) for r in out.itertuples()]
    return out.drop(columns=["camp_l7d_spend", "camp_l7d_sales", "camp_l7d_clicks", "camp_l7d_orders"])

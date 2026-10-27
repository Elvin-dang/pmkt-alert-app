"""Tier 1 – PL pacing vs monthly target (port of PL_Alert columns I–Q)."""
import pandas as pd

from . import (BUDGET_CAP, CHECK, MAINTAIN, NO_PLAN, NOT_RUNNING, OPTIMIZE_ACOS, PL_SCALE_UP, SCALE_DOWN, div)


def _action(r, p) -> str:
    if r.target_gmv == 0:
        return NO_PLAN
    if r.target_spend > 0 and r.spend_pace < p["not_running"]:
        return NOT_RUNNING
    if r.tacos_ratio > p["tacos_over"] and r.spend_pace > p["spend_pace_high"]:
        return SCALE_DOWN
    if r.tacos_ratio > p["tacos_over"]:
        return OPTIMIZE_ACOS
    if r.gmv_pace < p["gmv_pace_low"] and r.spend_pace < p["spend_pace_low"] and r.tacos_ratio <= 1:
        return PL_SCALE_UP
    if r.pct_spend >= p["budget_cap"]:
        return BUDGET_CAP
    if r.gmv_pace < p["gmv_pace_low"]:
        return CHECK
    return MAINTAIN


def _sev(action: str, spend_mtd: float) -> str:
    if action in (SCALE_DOWN, BUDGET_CAP) or (action == NO_PLAN and spend_mtd > 100):
        return "HIGH"
    if action in (MAINTAIN, NO_PLAN):
        return "LOW"
    return "MED"


def pacing(pl: pd.DataFrame, time_gone: float, p: dict) -> pd.DataFrame:
    out = pl.copy()
    out["actual_tacos"] = [div(s, g) for s, g in zip(out.spend_mtd, out.gmv_mtd)]
    out["pct_gmv"] = [div(a, t) for a, t in zip(out.gmv_mtd, out.target_gmv)]
    out["pct_spend"] = [div(a, t) for a, t in zip(out.spend_mtd, out.target_spend)]
    out["tacos_ratio"] = [div(a, t) for a, t in zip(out.actual_tacos, out.target_tacos)]
    out["gmv_pace"] = out["pct_gmv"] / time_gone
    out["spend_pace"] = out["pct_spend"] / time_gone
    out["pacing_action"] = [_action(r, p) for r in out.itertuples()]
    out["pacing_sev"] = [_sev(a, s) for a, s in zip(out.pacing_action, out.spend_mtd)]
    out["pacing_reason"] = [
        f"GMV {r.pct_gmv:.0%} | Spend {r.pct_spend:.0%} | TACoS {r.actual_tacos:.1%} vs target "
        f"{r.target_tacos:.1%} | time gone {time_gone:.0%}" for r in out.itertuples()]
    return out

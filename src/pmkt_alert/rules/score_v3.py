"""Score model (team v3 logic): Department frame → PIC / PL weighted TACoS score → action code.
Port of PIC_Alert / PL_Alert columns E–AQ and Config J (C66–C75) of Alert_Logic_System_Team_v3."""
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from . import div

NO_DATA, NO_PLAN, NOT_RUNNING, TOO_EARLY = "NO DATA", "NO PLAN", "KHÔNG CHẠY", "CHƯA ĐỦ DATA"
SCALE_DOWN, OPTIMIZE, SCALE_UP, MAINTAIN, BUDGET_CAP = "SCALE DOWN", "OPTIMIZE", "SCALE UP", "MAINTAIN", "BUDGET CAP"
REGIME_NA, REGIME_ROOM, REGIME_OVER, REGIME_CLOSE = "N/A (thiếu data)", "CÒN ROOM", "VƯỢT", "SÁT NGƯỠNG"


def _clamp(x: float) -> float:
    return max(-100.0, min(100.0, x))


def _round(x: float) -> int:  # Excel TEXT(x,"0") rounds half away from zero
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _money(x: float) -> str:  # TEXT(x,"$#,##0;-$#,##0")
    n = _round(abs(x))
    return f"{'-' if x < 0 and n else ''}${n:,}"


def department(rows: pd.DataFrame, pics: pd.DataFrame, p: dict) -> dict:
    """Totals over the in-scope rows (Config C66–C75). `pics` = one row per PIC with gmv_mtd, for coverage."""
    tg, ts = float(rows["target_gmv"].sum()), float(rows["target_spend"].sum())
    ag, sp, ads = float(rows["gmv_mtd"].sum()), float(rows["spend_mtd"].sum()), float(rows["ads_gmv_mtd"].sum())
    target_tacos, actual_tacos = div(ts, tg), div(sp, ag)
    coverage = div(float((pics["gmv_mtd"] > 0).sum()), float(len(pics)))
    if coverage < 1:
        regime = REGIME_NA
    elif actual_tacos <= 0.95 * target_tacos:
        regime = REGIME_ROOM
    elif actual_tacos > target_tacos:
        regime = REGIME_OVER
    else:
        regime = REGIME_CLOSE
    shift = p["sd_room"] if regime == REGIME_ROOM else p["sd_over"] if regime == REGIME_OVER else 0
    return {"target_gmv": tg, "target_spend": ts, "target_tacos": target_tacos, "actual_gmv": ag, "actual_spend": sp,
            "actual_tacos": actual_tacos, "coverage": coverage, "regime": regime, "benchmark": div(ads, ag),
            "sd_threshold": p["score_sd"] + shift}


def _code(r, dept: dict, time_gone: float, p: dict) -> str:
    if r.gmv_mtd == 0 and r.spend_mtd == 0:
        return NO_DATA
    if r.target_gmv == 0:
        return NO_PLAN
    if r.target_spend > 0 and r.spend_pace < p["not_running"]:
        return NOT_RUNNING
    if time_gone < p["min_time_gone"] or r.spend_mtd < p["min_spend"]:
        return TOO_EARLY
    if r.score >= dept["sd_threshold"]:
        return OPTIMIZE if r.excess_dept <= 0 else SCALE_DOWN
    if r.score >= p["score_opt"]:
        return OPTIMIZE
    if r.score <= p["score_up"]:
        return SCALE_UP if r.excess_dept <= 0 else MAINTAIN
    return MAINTAIN


def _sev(code: str, spend: float) -> str:
    if code in (NO_DATA, TOO_EARLY):
        return ""
    if code in (SCALE_DOWN, BUDGET_CAP) or (code == NO_PLAN and spend > 100):
        return "HIGH"
    if code in (MAINTAIN, NO_PLAN):
        return "LOW"
    return "MED"


def score_rows(df: pd.DataFrame, dept: dict, time_gone: float, p: dict) -> pd.DataFrame:
    """Adds the 6 factor scores, SCORE, base_code and (as pacing_* for the shared campaign tier) the action code,
    severity and reason. Expects trend() to have run (d_tacos)."""
    out = df.copy()
    dt = dept["target_tacos"]
    out["target_tacos"] = [div(s, g) for s, g in zip(out.target_spend, out.target_gmv)]
    out["actual_tacos"] = [div(s, g) for s, g in zip(out.spend_mtd, out.gmv_mtd)]
    out["pct_gmv"] = [div(a, t) for a, t in zip(out.gmv_mtd, out.target_gmv)]
    out["pct_spend"] = [div(a, t) for a, t in zip(out.spend_mtd, out.target_spend)]
    out["gmv_pace"] = out["pct_gmv"] / time_gone
    out["spend_pace"] = out["pct_spend"] / time_gone
    out["tacos_ratio"] = [div(a, t) for a, t in zip(out.actual_tacos, out.target_tacos)]
    out["share_dept_target"] = out["target_gmv"] / dept["target_gmv"] if dept["target_gmv"] else 0.0
    out["excess_dept"] = out["spend_mtd"] - dt * out["gmv_mtd"]
    out["excess_own"] = out["spend_mtd"] - out["target_tacos"] * out["gmv_mtd"]
    out["ads_dep"] = [div(a, g) for a, g in zip(out.ads_gmv_mtd, out.gmv_mtd)]
    st, bm = p["sens_tacos"], dept["benchmark"]
    out["s1"] = [0.0 if not t or not g else _clamp((a / t - 1) / st * 100)
                 for a, t, g in zip(out.actual_tacos, out.target_tacos, out.gmv_mtd)]
    out["s2"] = [0.0 if not dt or not g else _clamp((a / dt - 1) / st * 100) for a, g in zip(out.actual_tacos, out.gmv_mtd)]
    out["s3"] = [0.0 if not g or not bm else -_clamp((d / bm - 1) / p["sens_ads"] * 100) for d, g in zip(out.ads_dep, out.gmv_mtd)]
    out["s4"] = [0.0 if d is None else _clamp(d / p["sens_trend"] * 100) for d in out.d_tacos]
    out["s5"] = [0.0 if not t else _clamp((pace - 1) / p["sens_gmv"] * 100) for pace, t in zip(out.gmv_pace, out.target_gmv)]
    out["s6"] = [0.0 if not t else _clamp((pace - 1) / p["sens_spend"] * 100) for pace, t in zip(out.spend_pace, out.target_spend)]
    w = [p[f"w{i}"] for i in range(1, 7)]
    out["score"] = pd.Series([None if g == 0 and s == 0 else
                              sum(wi * r[f"s{i}"] for i, wi in enumerate(w, 1)) / sum(w)
                              for g, s, (_, r) in zip(out.gmv_mtd, out.spend_mtd, out.iterrows())], index=out.index, dtype=object)
    out["base_code"] = [_code(r, dept, time_gone, p) for r in out.itertuples()]
    out["pacing_action"] = [BUDGET_CAP if c in (MAINTAIN, SCALE_UP) and ps >= p["budget_cap"] else c
                            for c, ps in zip(out.base_code, out.pct_spend)]
    out["pacing_sev"] = [_sev(c, s) for c, s in zip(out.pacing_action, out.spend_mtd)]
    out["pacing_reason"] = [
        "" if sev == "" else "Có spend/GMV nhưng chưa có target" if c == NO_PLAN else
        f"TACoS {r.actual_tacos:.1%} | target riêng {r.target_tacos:.1%} | target Dept {dt:.1%} | Excess$ vs Dept "
        f"{_money(r.excess_dept)} | GMV pace {r.gmv_pace:.2f} | Spend pace {r.spend_pace:.2f} | score {_round(r.score)}"
        for r, c, sev in zip(out.itertuples(), out.pacing_action, out.pacing_sev)]
    return out

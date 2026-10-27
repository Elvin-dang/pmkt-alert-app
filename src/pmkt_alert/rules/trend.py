"""Tier 2 – PL trend L7D vs P7D through the 27-combination Matrix_PL (port of PL_Alert X–AF)."""
import pandas as pd


def direction(x: float | None, thr: float) -> str:
    if x is None:
        return "F"
    if x >= thr:
        return "U"
    if x <= -thr:
        return "D"
    return "F"


def _ratio_change(l_spend, l_base, p_spend, p_base):
    if not p_spend or not p_base:
        return None
    if not l_base:
        return 9.99
    return (l_spend / l_base) / (p_spend / p_base) - 1


def trend(pl: pd.DataFrame, p: dict, matrix: dict) -> pd.DataFrame:
    out = pl.copy()
    d_spend = [None if not ps else ls / ps - 1 for ls, ps in zip(out.l7d_spend, out.p7d_spend)]
    d_acos = [_ratio_change(r.l7d_spend, r.l7d_ads_gmv, r.p7d_spend, r.p7d_ads_gmv) for r in out.itertuples()]
    d_tacos = [_ratio_change(r.l7d_spend, r.l7d_gmv, r.p7d_spend, r.p7d_gmv) for r in out.itertuples()]
    out["d_spend"] = pd.Series(d_spend, index=out.index, dtype=object)
    out["d_acos"] = pd.Series(d_acos, index=out.index, dtype=object)
    out["d_tacos"] = pd.Series(d_tacos, index=out.index, dtype=object)
    keys = [f"{direction(s, p['trend_spend'])}|{direction(a, p['trend_acos'])}|{direction(t, p['trend_tacos'])}"
            for s, a, t in zip(d_spend, d_acos, d_tacos)]
    out["trend_key"] = keys
    labels = ["" if spend < p["trend_min_spend"] else matrix.get(k, ("", ""))[0] for k, spend in zip(keys, out.l7d_spend)]
    out["trend_label"] = labels
    out["trend_action"] = [matrix.get(k, ("", ""))[1] if lab else "" for k, lab in zip(keys, labels)]
    return out

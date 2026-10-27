import math

import pandas as pd
import pytest

from factory import MATRIX_LABELS
from pmkt_alert.rules.pacing import pacing
from pmkt_alert.rules.trend import direction, trend

P = {"gmv_pace_low": 0.85, "spend_pace_low": 0.9, "spend_pace_high": 1.15, "tacos_over": 1.1, "not_running": 0.1,
     "budget_cap": 1.0, "trend_spend": 0.2, "trend_acos": 0.2, "trend_tacos": 0.2, "trend_min_spend": 50}
MATRIX = {f"{s}|{a}|{t}": (MATRIX_LABELS.get(f"{s}|{a}|{t}", ""), "hint" if f"{s}|{a}|{t}" in MATRIX_LABELS else "")
          for s in "UFD" for a in "UFD" for t in "UFD"}
TG = 0.612903225806452


def one(**kw):
    base = dict(pl="PL", pic="P", target_gmv=1000.0, target_spend=100.0, target_tacos=0.1, gmv_mtd=600.0, spend_mtd=60.0,
                l7d_spend=100.0, p7d_spend=100.0, l7d_ads_gmv=500.0, p7d_ads_gmv=500.0, l7d_gmv=1000.0, p7d_gmv=1000.0)
    base.update(kw)
    if "target_tacos" not in kw:
        base["target_tacos"] = base["target_spend"] / base["target_gmv"] if base["target_gmv"] else 0.0
    return pd.DataFrame([base])


@pytest.mark.parametrize("kw,action,sev", [
    (dict(target_gmv=0, target_spend=0, spend_mtd=50), "NO PLAN – kiểm tra target", "LOW"),
    (dict(spend_mtd=1), "KHÔNG CHẠY – spend ~0 so với plan", "MED"),
    (dict(spend_mtd=90, gmv_mtd=600), "SCALE DOWN – overspend + TACoS vượt", "HIGH"),
    (dict(spend_mtd=70, gmv_mtd=600), "OPTIMIZE ACoS – TACoS vượt target", "MED"),
    (dict(spend_mtd=40, gmv_mtd=450), "SCALE UP – còn room, TACoS trong target", "MED"),
    (dict(spend_mtd=100, gmv_mtd=1000), "BUDGET CAP – đã dùng hết budget tháng", "HIGH"),
    (dict(spend_mtd=50, gmv_mtd=480), "CHECK – GMV thiếu nhưng spend không thấp (listing/stock/giá?)", "MED"),
    (dict(spend_mtd=60, gmv_mtd=620), "MAINTAIN", "LOW"),
])
def test_pacing_branches(kw, action, sev):
    r = pacing(one(**kw), TG, P).iloc[0]
    assert (r.pacing_action, r.pacing_sev) == (action, sev)


def test_workbook_row_scale_up():
    r = pacing(one(target_gmv=368160, target_spend=26238, gmv_mtd=167583.92, spend_mtd=11419.19), TG, P).iloc[0]
    assert r.pacing_action == "SCALE UP – còn room, TACoS trong target" and r.pacing_sev == "MED"
    assert round(r.gmv_pace, 6) == 0.742684 and round(r.spend_pace, 6) == 0.710089
    assert r.pacing_reason == "GMV 46% | Spend 44% | TACoS 6.8% vs target 7.1% | time gone 61%"


def test_no_plan_high_when_spending():
    r = pacing(one(target_gmv=0, target_spend=0, gmv_mtd=10396.49, spend_mtd=2602.93), TG, P).iloc[0]
    assert r.pacing_action.startswith("NO PLAN") and r.pacing_sev == "HIGH"


def test_zero_division_is_safe():
    r = pacing(one(target_gmv=0, target_spend=0, gmv_mtd=0, spend_mtd=0), 0.5, P).iloc[0]
    assert r.pacing_sev == "LOW" and math.isfinite(r.tacos_ratio)


def test_direction():
    assert [direction(None, 0.2), direction(0.2, 0.2), direction(-0.2, 0.2), direction(0.19, 0.2)] == ["F", "U", "D", "F"]


def test_trend_9_99_and_floor():
    t = trend(one(l7d_spend=100, p7d_spend=50, l7d_ads_gmv=0, p7d_ads_gmv=500, l7d_gmv=1000, p7d_gmv=1000), P, MATRIX).iloc[0]
    assert t.d_acos == 9.99 and t.trend_key == "U|U|U" and t.trend_label == "REVIEW ADS" and t.trend_action == "hint"
    t2 = trend(one(l7d_spend=40, p7d_spend=10, l7d_ads_gmv=1, p7d_ads_gmv=1, l7d_gmv=1, p7d_gmv=1), P, MATRIX).iloc[0]
    assert t2.trend_label == "" and t2.trend_action == ""


def test_trend_p7d_zero_is_flat():
    t = trend(one(l7d_spend=2439.87, p7d_spend=0, l7d_ads_gmv=7217.69, p7d_ads_gmv=0, l7d_gmv=8624.04, p7d_gmv=349.89), P, MATRIX).iloc[0]
    assert t.d_spend is None and t.trend_key == "F|F|F" and t.trend_label == ""


def test_workbook_row_trend():  # PL_Alert row 5: Δ Spend −54.5%, Δ ACoS +19.2% → D|F|?
    t = trend(one(l7d_spend=2818.48, p7d_spend=6197.81, l7d_ads_gmv=16643.99, p7d_ads_gmv=43623.52,
                  l7d_gmv=33709.09, p7d_gmv=101146.01), P, MATRIX).iloc[0]
    assert round(t.d_spend, 6) == -0.545246 and round(t.d_acos, 6) == 0.1919
    assert t.trend_key.startswith("D|F|")

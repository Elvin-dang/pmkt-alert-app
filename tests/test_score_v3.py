import pandas as pd
import pytest

from pmkt_alert.logic import DEFAULT_PARAMS, DEFAULT_V3
from pmkt_alert.rules.score_v3 import department, score_rows
from pmkt_alert.rules.trend import trend

P = {**DEFAULT_PARAMS, **DEFAULT_V3}
TG = 0.6129032258064516
# Department as computed in the v3 workbook (Config C66–C75 cached values)
DEPT = {"target_gmv": 1895334, "target_spend": 133197, "target_tacos": 0.07027626792955753,
        "actual_gmv": 459069.43, "actual_spend": 35511.91, "actual_tacos": 0.07735629444983955,
        "coverage": 0.2857142857142857, "regime": "N/A (thiếu data)", "benchmark": 0.5706350126602852, "sd_threshold": 50}


def row(**kw):
    return pd.DataFrame([kw])


def test_pl_row_matches_workbook():  # PL_Alert row 5
    pl = row(target_gmv=368160, target_spend=26238, gmv_mtd=163751.01, spend_mtd=11260.24, ads_gmv_mtd=75746.56,
             l7d_spend=2818.48, p7d_spend=6197.81, l7d_ads_gmv=16643.99, p7d_ads_gmv=43623.52,
             l7d_gmv=33709.09, p7d_gmv=101146.01)
    r = score_rows(trend(pl, P, {"D|F|U": ("REVIEW SKU", "x")}), DEPT, TG, P).iloc[0]
    assert r.s1 == pytest.approx(-7.025675647388785) and r.s2 == pytest.approx(-4.302640653068601)
    assert r.s3 == pytest.approx(37.87480654433863) and r.s4 == pytest.approx(72.90307016237998)
    assert r.s5 == pytest.approx(-91.43424912509434) and r.s6 == pytest.approx(-59.959062990199044)
    assert r.score == pytest.approx(-8.229701408465838) and r.excess_dept == pytest.approx(-247.56985249565514)
    assert (r.base_code, r.pacing_action, r.pacing_sev) == ("MAINTAIN", "MAINTAIN", "LOW")
    assert r.pacing_reason == "TACoS 6.9% | target riêng 7.1% | target Dept 7.0% | Excess$ vs Dept -$248 | GMV pace 0.73 | Spend pace 0.70 | score -8"


def test_pic_row_matches_workbook():  # PIC_Alert row 5
    pic = row(target_gmv=748633, target_spend=48913, gmv_mtd=452741.38, spend_mtd=35196.76, ads_gmv_mtd=259384.79,
              l7d_spend=9998.98, p7d_spend=18658.15, l7d_ads_gmv=63798.31, p7d_ads_gmv=145997.45,
              l7d_gmv=120616.69, p7d_gmv=265645.4)
    r = score_rows(trend(pic, P, {}), DEPT, TG, P).iloc[0]
    assert r.score == pytest.approx(22.065705839847627, abs=1e-6) and r.pacing_action == "MAINTAIN"
    assert r.excess_dept == pytest.approx(3379.7854763223804, abs=1e-4)


@pytest.mark.parametrize("kw,code,sev", [
    (dict(gmv_mtd=0, spend_mtd=0), "NO DATA", ""),
    (dict(target_gmv=0, target_spend=0, spend_mtd=500), "NO PLAN", "HIGH"),
    (dict(spend_mtd=1), "KHÔNG CHẠY", "MED"),
    (dict(spend_mtd=40, target_spend=60), "CHƯA ĐỦ DATA", ""),
])
def test_hard_rules(kw, code, sev):
    base = dict(target_gmv=10000, target_spend=1000, gmv_mtd=6000, spend_mtd=600, ads_gmv_mtd=3000, l7d_spend=100,
                p7d_spend=100, l7d_ads_gmv=500, p7d_ads_gmv=500, l7d_gmv=1000, p7d_gmv=1000)
    base.update(kw)
    r = score_rows(trend(row(**base), P, {}), DEPT, TG, P).iloc[0]
    assert (r.pacing_action, r.pacing_sev) == (code, sev)


def test_gates_and_budget_cap():
    hi = dict(target_gmv=10000, target_spend=500, gmv_mtd=3000, spend_mtd=600, ads_gmv_mtd=600, l7d_spend=300,
              p7d_spend=100, l7d_ads_gmv=500, p7d_ads_gmv=500, l7d_gmv=800, p7d_gmv=1000)
    r = score_rows(trend(row(**hi), P, {}), DEPT, TG, P).iloc[0]
    assert r.score >= 50 and r.excess_dept > 0 and r.pacing_action == "SCALE DOWN" and r.pacing_sev == "HIGH"
    gated = score_rows(trend(row(**hi), P, {}), {**DEPT, "target_tacos": 0.5}, TG, P).iloc[0]
    assert gated.excess_dept <= 0 and gated.pacing_action == "OPTIMIZE"  # no SCALE DOWN when under the Dept frame


def test_department_regime_and_threshold():
    pics = pd.DataFrame({"pic": ["A", "B"], "gmv_mtd": [100.0, 50.0]})
    rows = pd.DataFrame({"target_gmv": [1000.0], "target_spend": [70.0], "gmv_mtd": [150.0], "spend_mtd": [9.0],
                         "ads_gmv_mtd": [60.0]})
    d = department(rows, pics, P)
    assert d["coverage"] == 1 and d["regime"] == "CÒN ROOM" and d["sd_threshold"] == 65 and d["benchmark"] == pytest.approx(0.4)
    d2 = department(rows.assign(spend_mtd=12.0), pics, P)
    assert d2["regime"] == "VƯỢT" and d2["sd_threshold"] == 40
    d3 = department(rows, pics.assign(gmv_mtd=[100.0, 0.0]), P)
    assert d3["regime"] == "N/A (thiếu data)" and d3["sd_threshold"] == 50

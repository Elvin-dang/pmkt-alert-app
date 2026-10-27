import pandas as pd

from pmkt_alert.rules.campaign import campaign

P = {"camp_cut": 1.15, "camp_good": 1.0, "camp_optimize": 1.3, "min_clicks": 15, "excess_high": 30,
     "trend_spend": 0.2, "trend_acos": 0.2}
K = {"SPS_PRODUCTS": 3, "SPS_BRANDS": 3, "SPS_DISPLAY": 5}


def run_one(pl_action="MAINTAIN", pl_acos=0.15, pl_cr=0.05, **kw):
    c = dict(campaign="C", campaign_id="1", pl="PL", type="SPS_PRODUCTS", l7d_spend=50.0, l7d_clicks=200.0,
             l7d_sales=400.0, l7d_orders=10.0, p7d_spend=50.0, p7d_sales=400.0, l3d_spend=20.0, l3d_sales=160.0)
    c.update(kw)
    # PL frame whose camp_l7d_* reproduce the requested pl_acos / pl_cr
    pl = pd.DataFrame([dict(pl="PL", pic="PIC A", pacing_action=pl_action, camp_l7d_spend=pl_acos * 1000,
                            camp_l7d_sales=1000.0 if pl_acos else 0.0, camp_l7d_clicks=1000.0 if pl_cr else 0.0,
                            camp_l7d_orders=pl_cr * 1000)])
    return campaign(pd.DataFrame([c]), pl, P, K).iloc[0]


def test_workbook_row_5():
    r = run_one(type="SPS_PRODUCTS", l7d_spend=642.19, l7d_clicks=1832, l7d_sales=3013.29, l7d_orders=105,
                p7d_spend=1072.93, p7d_sales=6762.54, l3d_spend=235.88, l3d_sales=1172.44,
                pl_action="SCALE UP – còn room, TACoS trong target", pl_acos=0.175324505765747, pl_cr=0.056881176187033)
    assert r.min_clicks == 53 and r.enough and r.pic == "PIC A" and r.unit_id == "camp:1:PL"
    assert round(r.excess, 2) == 113.89
    assert r.camp_trend == "XẤU ĐI 7D: ACoS ↑" and r.base_action == "MAINTAIN" and r.sev == "MED"


def test_pause_is_high():
    r = run_one(l7d_clicks=100, l7d_orders=0, l7d_sales=0, l7d_spend=80, pl_cr=0.05, pl_acos=0.15)
    assert r.base_action.startswith("PAUSE") and r.sev == "HIGH" and r.l7d_acos is None


def test_cut_high_needs_excess():
    hi = run_one(l7d_spend=200, l7d_sales=500, pl_acos=0.2, pl_action="SCALE DOWN – overspend + TACoS vượt")
    assert hi.base_action.startswith("CUT") and hi.sev == "HIGH"  # excess 100 ≥ 30
    lo = run_one(l7d_spend=26, l7d_sales=100, pl_acos=0.2, pl_action="SCALE DOWN – overspend + TACoS vượt")
    assert lo.base_action.startswith("CUT") and lo.sev == "MED"  # excess 6


def test_push_watch_scaleup_optimize():
    sd = "SCALE DOWN – overspend + TACoS vượt"
    assert run_one(l7d_spend=20, l7d_sales=200, pl_acos=0.15, pl_action=sd).base_action == "MAINTAIN/PUSH – ACoS dưới PL avg"
    assert run_one(l7d_spend=32, l7d_sales=200, pl_acos=0.15, pl_action=sd).base_action == "WATCH"
    su = "SCALE UP – còn room, TACoS trong target"
    r = run_one(l7d_spend=20, l7d_sales=200, pl_acos=0.15, pl_action=su)
    assert r.base_action == "SCALE UP – tăng bid/budget" and r.sev == "MED"
    assert run_one(l7d_spend=50, l7d_sales=200, pl_acos=0.15, pl_action=su).base_action == "OPTIMIZE – ACoS cao"
    assert run_one(l7d_spend=50, l7d_sales=200, pl_acos=0.15).base_action == "OPTIMIZE – ACoS cao"
    assert run_one(pl_action="NO PLAN – kiểm tra target").base_action == "CHECK PLAN – PL chưa có target"


def test_wait_when_not_enough_clicks():
    r = run_one(l7d_clicks=5, pl_cr=0.05)
    assert r.base_action == "WAIT – chưa đủ click" and r.sev == ""


def test_min_clicks_by_type():
    assert run_one(type="SPS_DISPLAY", pl_cr=0.05).min_clicks == 100
    assert run_one(type="DSP", pl_cr=0.05).min_clicks == 60  # unknown type falls back to SPS_PRODUCTS k


def test_zero_pl_acos_follows_excel_text_comparison():
    # Excel: a "" ratio compared with ">" a number is TRUE, so OPTIMIZE (not MAINTAIN).
    r = run_one(pl_acos=0, pl_cr=0, l7d_clicks=20, l7d_orders=1, l7d_sales=10, l7d_spend=5)
    assert r.acos_ratio is None and r.base_action == "OPTIMIZE – ACoS cao" and r.min_clicks == 15
    assert r.excess == 5.0

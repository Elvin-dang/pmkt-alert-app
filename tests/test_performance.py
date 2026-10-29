"""Performance Review (Performance Review_brief): tiles, PL / SKU / campaign tables and daily chart series.
Synthetic v4 data: per ASIN-day GMV 100, ads GMV 40, spend 1+2+3 = 6, units 3, ads units 1; Oct targets per ASIN:
PL Alpha GMV 5000 / spend 300, PL Beta 3000 / 100; daily GMV contribution 1/31."""
from datetime import date

import pytest

from factory import make_all_v4
from pmkt_alert.loaders import detect_inputs, load_inputs
from pmkt_alert.logic import load_logic
from pmkt_alert.performance import performance
from pmkt_alert.pipeline import result_to_json, run_rules


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    files = make_all_v4(tmp_path_factory.mktemp("perf"))
    inp = load_inputs(detect_inputs(list(files.values())))
    logic = load_logic(files["logic"])
    rj = result_to_json(run_rules(inp, logic, date(2026, 10, 19)))
    return inp, rj, logic


def test_summary_tiles_are_for_the_pic(data):
    inp, rj, logic = data
    out = performance(inp, rj, "Team X", pic="PIC A", pl="PL Alpha")  # the PL filter does not change the tiles
    t = out["summary"]
    assert out["filters"]["start"] == "2026-10-01" and out["filters"]["end"] == "2026-10-19"
    assert t["time_gone"] == pytest.approx(19 / 31) and t["campaign_gone"] == pytest.approx(19 / 31)
    assert t["gmv"] == 7600 and t["gmv_target"] == 16000 and t["gmv_pct"] == pytest.approx(0.475)
    assert t["spend"] == 456 and t["spend_target"] == 800 and t["spend_pct"] == pytest.approx(0.57)
    assert t["ads_nmv"] == 3040 and t["acos"] == pytest.approx(456 / 3040) and t["tacos"] == pytest.approx(0.06)
    assert t["ads_rs_share"] == pytest.approx(1 / 3)


def test_pl_and_sku_tables(data):
    inp, rj, logic = data
    out = performance(inp, rj, "Team X", pic="PIC A")
    pls = {r["pl"]: r for r in out["pls"]}
    assert set(pls) == {"PL Alpha", "PL Beta"}
    a = pls["PL Alpha"]
    assert (a["target"]["gmv"], a["actual"]["gmv"], a["target"]["rs"], a["actual"]["rs"]) == (10000, 3800, 180, 114)
    assert a["achieve"]["gmv"] == pytest.approx(0.38) and a["action"] and a["reason"]
    skus = {r["sku"]: r for r in out["skus"]}
    assert set(skus) == {"S001", "S002", "S003", "S004"}
    s3 = skus["S003"]
    assert s3["ineligible"] == {"current": "INELIGIBLE", "changes": 1, "days": 2} and s3["stock"] == 500
    assert skus["S001"]["ineligible"]["current"] == "" and skus["S001"]["actual"]["gmv"] == 1900


def test_listing_issue_and_pl_filter(data):
    inp, rj, logic = data
    out = performance(inp, rj, "Team X", pic="PIC B")
    s5 = next(r for r in out["skus"] if r["sku"] == "S005")
    assert "Inactive" in s5["listing_issue"]
    only = performance(inp, rj, "Team X", pic="PIC A", pl="PL Beta")
    assert {r["sku"] for r in only["skus"]} == {"S003", "S004"} and {r["pl"] for r in only["pls"]} == {"PL Alpha", "PL Beta"}
    assert all(c["pl"] == "PL Beta" for c in only["campaigns"])


def test_daily_series_and_campaigns(data):
    inp, rj, logic = data
    out = performance(inp, rj, "Team X", pic="PIC A", pl="PL Alpha", start="2026-10-10", end="2026-10-19")
    d = out["daily"]
    assert [x["date"] for x in d][0] == "2026-10-10" and len(d) == 10
    assert d[0]["gmv"] == 200 and d[0]["gmv_target"] == pytest.approx(10000 / 31) and d[0]["ads_nmv"] == 80
    assert d[0]["spend_target"] == pytest.approx(600 * 0.05) and d[0]["tacos"] == pytest.approx(12 / 200)
    assert out["summary"]["gmv"] == 4000 and out["summary"]["gmv_target"] == 16000  # timeframe actual vs month target
    camps = {c["campaign"]: c for c in out["campaigns"]}
    alpha = next(c for k, c in camps.items() if k.startswith("Camp Alpha"))
    assert alpha["spend"] == 50 and alpha["nmv"] == 300 and alpha["orders"] == 10 and alpha["acos"] == pytest.approx(50 / 300)
    assert alpha["alert"] is True and "trend_spend" in alpha and "last_action" in alpha


def test_pl_with_target_but_no_sales(data):
    import dataclasses
    inp, rj, logic = data
    no_beta = dataclasses.replace(inp, raw=inp.raw[~inp.raw["asin"].isin(["B000000003", "B000000004"])])
    beta = next(r for r in performance(no_beta, rj, "Team X", pic="PIC A")["pls"] if r["pl"] == "PL Beta")
    assert beta["actual"]["tacos"] is None and beta["achieve"]["tacos"] is None and beta["achieve"]["gmv"] == 0


def test_ineligible_judged_at_the_end_date_not_the_newest_log(data):
    inp, rj, logic = data
    # the log runs to 19/10; viewing up to 18/10 must still see 18/10's status
    s3 = next(r for r in performance(inp, rj, "Team X", pic="PIC A", end="2026-10-18")["skus"] if r["sku"] == "S003")
    assert s3["ineligible"] == {"current": "INELIGIBLE", "changes": 1, "days": 1}


def test_listing_issue_ignores_normal_lifecycle_stages():
    from pmkt_alert.performance import _listing_issue
    assert _listing_issue({"status": "Active", "lifecycle": "Introduction"}) == ""
    assert _listing_issue({"status": "Active", "lifecycle": "Turnkey"}) == ""
    assert _listing_issue({"status": "Inactive", "lifecycle": "Withdrawal"}) == "Inactive · Withdrawal"

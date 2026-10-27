from datetime import date

import pytest

from pmkt_alert.evidence import evidence, row_ranges
from pmkt_alert.pipeline import result_to_json, run_rules


@pytest.fixture(scope="module")
def rj(loaded, logic):
    return result_to_json(run_rules(loaded, logic, date(2026, 10, 19)))


def test_row_ranges():
    assert row_ranges([5, 3, 4, 10, 12, 11, 20]) == "3–5, 10–12, 20"
    assert row_ranges([]) == ""


def _section(ev, key):
    return next(s for s in ev["sections"] if s["key"] == key)


def test_pl_evidence_totals_match_result(loaded, logic, rj):
    row = next(r for r in rj["pl"] if r["pl"] == "PL Alpha")
    ev = evidence(loaded, logic, rj, "pl:PL Alpha")
    mtd = _section(ev, "raw_mtd")
    assert mtd["source"] == "tracker.xlsx › raw_sso_us" and mtd["row_count"] == 2 * 19
    assert mtd["totals"]["gmv"] == pytest.approx(row["gmv_mtd"]) and mtd["totals"]["spend"] == pytest.approx(row["spend_mtd"])
    assert "sp_spend" in mtd["columns_text"] and len(mtd["rows"]) <= 20 and "_row" in mtd["rows"][0]
    kpi = _section(ev, "kpi")
    assert kpi["totals"]["gmv"] == pytest.approx(row["target_gmv"])
    assert {t["key"] for t in ev["thresholds"]} >= {"gmv_pace_low", "tacos_over"}
    assert all(t["cell"].startswith("Config!C") for t in ev["thresholds"] if t["key"] != "matrix")
    assert any("GMV pace" in c["label"] for c in ev["calc"])


def test_campaign_evidence_includes_activity_log(loaded, logic, rj):
    ev = evidence(loaded, logic, rj, "camp:100000000000001:PL Alpha")
    ads = _section(ev, "ads_l7d")
    row = next(r for r in rj["camp"] if r["unit_id"] == "camp:100000000000001:PL Alpha")
    assert ads["totals"]["spend"] == pytest.approx(row["l7d_spend"]) and ads["source"] == "ads.xlsx › ads_camp"
    log = _section(ev, "activity")
    assert log["row_count"] == 1 and log["rows"][0]["category"] == "Bid ↓" and log["rows"][0]["_row"] == 2
    assert any(t["key"] == "camp_cut" for t in ev["thresholds"])


def test_unknown_unit(loaded, logic, rj):
    with pytest.raises(ValueError):
        evidence(loaded, logic, rj, "pl:Nope")


def test_score_model_pic_and_pl_evidence(tmp_path, loaded):
    from factory import make_logic_v3
    from pmkt_alert.logic import load_logic
    lg = load_logic(make_logic_v3(tmp_path / "Alert_Logic_v3.xlsx"))
    rj3 = result_to_json(run_rules(loaded, lg, date(2026, 10, 19)))
    pic = next(p for p in rj3["pics"] if p["pic"] == "PIC A")
    ev = evidence(loaded, lg, rj3, "pic:PIC A")
    assert _section(ev, "raw_mtd")["totals"]["gmv"] == pytest.approx(pic["gmv_mtd"])
    assert any(c["label"] == "SCORE" for c in ev["calc"]) and ev["thresholds"][0]["key"] == "team_label"
    pl = evidence(loaded, lg, rj3, "pl:PL Alpha")
    assert any(c["label"].startswith("s1") for c in pl["calc"]) and "PMKT PIC_Final" in _section(pl, "mapping")["filter"]

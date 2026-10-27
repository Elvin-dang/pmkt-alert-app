import json
from datetime import date

import pandas as pd

from pmkt_alert.pipeline import result_to_json, run_rules
from pmkt_alert.rules.dataq import data_check
from pmkt_alert.rules.digest import digest


def test_pipeline_end_to_end(loaded, logic):
    r = run_rules(loaded, logic, date(2026, 10, 19))
    j = result_to_json(r)
    json.dumps(j, allow_nan=False)  # no NaN/inf leak
    assert {i.code for i in r.issues} >= {"UNMAPPED", "DUP_ASIN", "NO_PIC"}
    assert r.unreliable is True
    assert set(r.digest.pic) >= {"PIC A", "PIC B"}
    assert (r.camp.groupby("campaign_id").pl.nunique() > 1).any()
    assert j["as_of"] == "2026-10-19" and j["logic_version"] == 1
    assert all(row["unit_id"].startswith("pl:") for row in j["pl"])
    gamma = r.pl.set_index("pl").loc["PL Gamma"]
    assert gamma.pacing_action.startswith("NO PLAN") and gamma.trend_label == "REVIEW ADS"


def test_default_as_of_is_min_of_both_files(loaded, logic):
    assert run_rules(loaded, logic).as_of == min(loaded.raw.date.max(), loaded.ads.date.max())


def test_actions_flow_into_status(loaded, logic):
    camp = run_rules(loaded, logic, date(2026, 10, 19)).camp.set_index("unit_id")
    alpha = camp.loc["camp:100000000000001:PL Alpha"]
    assert alpha.last_action_type == "Bid ↓" and alpha.last_action_date == date(2026, 10, 18)


def test_spend_gap_and_clean_run():
    issues = data_check(unmapped_rows=0, unmapped_spend=0.0, ads_spend_mtd=100.0, raw_spend_mtd=102.0,
                        unmatched_camps=pd.DataFrame(columns=["campaign", "l7d_spend"]), duplicates=0, no_pic_pls=[],
                        log_skipped=0, log_empty=False)
    assert [i for i in issues if i.severity == "WARN"] == []
    gap = data_check(unmapped_rows=0, unmapped_spend=0.0, ads_spend_mtd=90.0, raw_spend_mtd=100.0,
                     unmatched_camps=pd.DataFrame(columns=["campaign", "l7d_spend"]), duplicates=0, no_pic_pls=[],
                     log_skipped=0, log_empty=True)
    assert {i.code for i in gap if i.severity == "WARN"} == {"SPEND_GAP", "LOG_EMPTY"}


def test_digest_counts():
    pl = pd.DataFrame({"pic": ["A", "A", "B"], "pacing_sev": ["HIGH", "MED", "LOW"], "trend_label": ["REVIEW ADS", "", "SCALE"]})
    camp = pd.DataFrame({"pic": ["A", "A", "A", "B"], "sev": ["HIGH", "MED", "HIGH", "MED"],
                         "status": ["CHƯA ACTION", "ACTION CŨ", "ĐÃ ACTION", "CHƯA ACTION"], "excess": [10.0, 5.0, 99.0, 1.0]})
    d = digest(pl, camp).set_index("pic")
    assert d.loc["A"].tolist() == [1, 1, 1, 1, 1, 1, 15.0]
    assert d.loc["B"].tolist() == [0, 0, 0, 0, 1, 0, 1.0]


def test_no_targets_for_month_warns():
    issues = data_check(unmapped_rows=0, unmapped_spend=0.0, ads_spend_mtd=100.0, raw_spend_mtd=100.0,
                        unmatched_camps=pd.DataFrame(columns=["campaign", "l7d_spend"]), duplicates=0, no_pic_pls=[],
                        log_skipped=0, log_empty=False, no_targets=True)
    assert [i.code for i in issues if i.severity == "WARN"] == ["NO_TARGETS"]


def test_pipeline_flags_missing_month_targets(loaded, logic):
    import dataclasses
    no_oct = dataclasses.replace(loaded, kpi=loaded.kpi[loaded.kpi.month != 10])
    r = run_rules(no_oct, logic, date(2026, 10, 19))
    assert "NO_TARGETS" in {i.code for i in r.issues} and r.unreliable

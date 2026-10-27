from datetime import date

import pytest

from pmkt_alert.pipeline import result_to_json, run_rules
from pmkt_alert.scorecard import METRICS, minmax_scores, scorecard, weekly


@pytest.fixture(scope="module")
def rj(loaded, logic):
    return result_to_json(run_rules(loaded, logic, date(2026, 10, 19)))


def test_minmax_scores_direction_and_ties():
    assert minmax_scores({"A": 1.0, "B": 0.5, "C": None}, higher_better=True) == {"A": 100.0, "B": 0.0, "C": None}
    assert minmax_scores({"A": 1.0, "B": 0.5}, higher_better=False) == {"A": 0.0, "B": 100.0}
    assert minmax_scores({"A": 2.0, "B": 2.0}, higher_better=True) == {"A": 100.0, "B": 100.0}


def test_scorecard_values_and_rank(rj):
    sc = scorecard(rj)
    a = next(p for p in sc["pics"] if p["pic"] == "PIC A")
    alpha = next(r for r in rj["pl"] if r["pl"] == "PL Alpha")
    beta = next(r for r in rj["pl"] if r["pl"] == "PL Beta")
    assert a["values"]["gmv_pct"] == pytest.approx((alpha["gmv_mtd"] + beta["gmv_mtd"]) / (alpha["target_gmv"] + beta["target_gmv"]))
    assert a["values"]["gmv_pace"] == pytest.approx(a["values"]["gmv_pct"] / sc["time_gone"])
    assert set(a["scores"]) == {m["key"] for m in METRICS}
    ranked = [p["pic"] for p in sc["pics"] if p["rank"]]
    assert ranked == sorted(ranked, key=lambda x: -next(p["total"] for p in sc["pics"] if p["pic"] == x))
    assert next(p for p in sc["pics"] if p["pic"] == "Chưa có PIC")["rank"] is None  # not ranked


def test_weights_change_total(rj):
    only_gmv = {m["key"]: 0 for m in METRICS} | {"gmv_pace": 1}
    sc = scorecard(rj, weights=only_gmv)
    for p in sc["pics"]:
        if p["scores"]["gmv_pace"] is not None:
            assert p["total"] == pytest.approx(p["scores"]["gmv_pace"])


def test_weekly_history(loaded, rj):
    w = weekly(loaded, date(2026, 10, 19))
    weeks = sorted({r["week"] for r in w})
    assert len(weeks) >= 3 and all(r["pic"] for r in w)
    row = next(r for r in w if r["pic"] == "PIC A" and r["week"] == weeks[-1])
    assert row["gmv"] > 0 and 0 < row["tacos"] < 1 and row["acos"] == pytest.approx(row["spend"] / row["ads_gmv"])


def test_action_rate_counts_only_recent_actions():
    from pmkt_alert.scorecard import _pic_values
    rj = {"as_of": "2026-10-19", "digest": [{"pic": "P", "excess_new": 0, "pl_high": 0, "camp_high": 0}], "pl": [],
          "camp": [{"pic": "P", "sev": "HIGH", "status": "CHƯA ACTION", "last_action_date": None},
                   {"pic": "P", "sev": "HIGH", "status": "ACTION CŨ", "last_action_date": "2026-09-30"},
                   {"pic": "P", "sev": "MED", "status": "ĐÃ ACTION", "last_action_date": "2026-10-18"}]}
    assert _pic_values(rj, "P", 0.6)["action_rate"] == pytest.approx(1 / 3)

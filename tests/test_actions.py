from datetime import date

import pandas as pd

from factory import FACTORY_LOG_CAMPAIGNS
from pmkt_alert.rules.actions import action_status, category, normalize_name, parse_activity, suggest_email_map

P = {"action_window": 3, "followup_days": 3, "improving_ratio": 0.9}


def test_normalize_strips_all_id_suffixes():
    assert normalize_name(" Amazon_X_SP_Auto_100525_1746859126_1777624167 ") == "amazon_x_sp_auto_100525"
    assert normalize_name("Camp_SB_Manual_KW_Exact_1791968495_1792727266") == "camp_sb_manual_kw_exact"


def test_parse_and_rename_alias(loaded):
    a = parse_activity(loaded.activity)
    assert a.attrs["skipped"] == 0 and not any("portfolio" in k for k in a.camp_key)
    assert a.camp_key.nunique() == FACTORY_LOG_CAMPAIGNS  # rename collapses two names into one key
    assert a.attrs["aliases"]["camp split_sp_old"] == "camp split_sp"
    budget = a[a.category == "Budget ↓"].iloc[0]
    assert budget.camp_key == "camp split_sp" and budget.action_date == date(2026, 10, 9)
    assert set(a.user) == {"pica@example.com", "picb@example.com"}


def test_unparseable_rows_counted():
    raw = pd.DataFrame([["1", "Campaign: X", "keywordTargetBid", "update", "$1", "$2", "not a date", "u"]],
                       columns=["id", "level", "type", "action", "from_", "to", "time", "user"])
    assert parse_activity(raw).attrs["skipped"] == 1


def test_category():
    assert category("keywordTargetBid", "update", "$0.8", "$0.72") == "Bid ↓"
    assert category("productTargetBid", "update", "$0.5", "$0.72") == "Bid ↑"
    assert category("campaignDailyBudget", "update", "$20", "$10") == "Budget ↓"
    assert category("campaignStatus", "update", "Enabled", "Paused") == "Pause"
    assert category("adGroupStatus", "update", "Paused", "Enabled") == "Enable"
    assert category("negativeTargeting", "create", "", "x") == "Negative"
    assert category("targeting", "create", "", "x") == "Tạo mới"
    assert category("bidAdjustmentByPlacement", "update", "Auto", "Increase: 10%") == "Bid ↑"
    assert category("campaignName", "update", "a", "b") == "Khác"


def test_email_map():
    m = suggest_email_map(["anhvt2@example.com", "binhnq@example.com", "x@example.com"],
                          ["Võ Thị Ánh", "Nguyễn Quốc Bình", "Đặng Văn Đức"])
    assert m == {"anhvt2@example.com": "Võ Thị Ánh", "binhnq@example.com": "Nguyễn Quốc Bình"}
    assert suggest_email_map(["ducdv@example.com"], ["Đặng Văn Đức"]) == {"ducdv@example.com": "Đặng Văn Đức"}


def _camp(**cols):
    return pd.DataFrame(cols)


def _acts(rows):
    return pd.DataFrame(rows, columns=["camp_key", "action_date", "category"]).assign(user="u")


def test_status_branches():
    camp = _camp(sev=["HIGH", "MED", "HIGH", "LOW"], camp_key=["a", "b", "c", "d"],
                 base_action=["CUT/OPTIMIZE – ACoS > PL avg"] * 4,
                 l7d_acos=pd.Series([0.2] * 4, dtype=object), l3d_acos=pd.Series([0.15, None, 0.25, 0.1], dtype=object))
    acts = _acts([("a", date(2026, 10, 18), "Bid ↓"), ("c", date(2026, 10, 10), "Budget ↓"), ("a", date(2026, 10, 25), "Pause")])
    r = action_status(camp, acts, date(2026, 10, 19), P).set_index("camp_key")
    assert r.loc["a"].status == "ĐÃ ACTION" and r.loc["a"].followup_due == date(2026, 10, 21)
    assert r.loc["a"].last_action_type == "Bid ↓"  # action after as-of ignored
    assert r.loc["a"].followup_check.startswith("Đang cải thiện")
    assert r.loc["a"].final_label == "ĐÃ ACTION (Bid ↓ 18/10) – follow up 21/10"
    assert r.loc["b"].status == "CHƯA ACTION" and r.loc["b"].final_label == "CUT/OPTIMIZE – ACoS > PL avg"
    assert r.loc["c"].status == "ACTION CŨ" and r.loc["c"].final_label == "ACTION CŨ (10/10) – alert còn → action lại: CUT/OPTIMIZE – ACoS > PL avg"
    assert r.loc["c"].followup_check.startswith("Chưa cải thiện")
    assert r.loc["d"].status == "" and r.loc["d"].final_label == ""


def test_status_uses_aliases_for_campaign_names(loaded):
    acts = parse_activity(loaded.activity)
    camp = _camp(campaign=["Camp Split_SP_Old"], sev=["HIGH"], base_action=["PAUSE/NEGATE – đủ click, 0 order"],
                 l7d_acos=pd.Series([None], dtype=object), l3d_acos=pd.Series([None], dtype=object))
    r = action_status(camp, acts, date(2026, 10, 19), P).iloc[0]
    assert r.camp_key == "camp split_sp" and r.status == "ACTION CŨ" and r.last_action_type == "Khác"

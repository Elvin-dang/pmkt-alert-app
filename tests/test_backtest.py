from datetime import date

from pmkt_alert.backtest import apply_approved, backtest, propose_from_feedback, proposals_from_review, with_changes
from pmkt_alert.store import Store


def test_with_changes_is_pure(logic):
    new = with_changes(logic, {"camp_good": 0.5, "matrix:F|F|F": "SCALE"})
    assert new.params["camp_good"] == 0.5 and new.matrix["F|F|F"][0] == "SCALE"
    assert logic.params["camp_good"] == 1.0 and logic.matrix["F|F|F"][0] == ""


def test_lowering_good_threshold_removes_scale_up_alerts(loaded, logic):
    b = backtest(loaded, logic, {"camp_good": 0.5}, date(2026, 10, 19), weeks=2)
    assert b["removed"]["MED"] >= 1 and b["added"]["HIGH"] == 0 and len(b["weeks"]) == 2
    assert b["weeks"][0]["as_of"] == "2026-10-19" and b["weeks"][1]["as_of"] == "2026-10-12"


def test_no_change_no_diff(loaded, logic):
    b = backtest(loaded, logic, {"camp_cut": logic.params["camp_cut"]}, date(2026, 10, 19), weeks=1)
    assert b["added"] == b["removed"] == {"HIGH": 0, "MED": 0, "TREND": 0}


def test_apply_approved_creates_next_version(tmp_path, logic):
    s = Store(tmp_path)
    s.import_logic(logic.path)
    fid = s.add_feedback({"unit_id": "pl:PL Alpha", "text": "x"})
    s.save_proposals([{"id": "p1", "param_key": "camp_cut", "old": 1.15, "new": 1.25, "status": "approved", "feedback_id": fid},
                      {"id": "p2", "param_key": "min_clicks", "old": 15, "new": 20, "status": "pending"}])
    out = apply_approved(s, logic)
    assert out.name == "Alert_Logic_Ver 2.xlsx" and s.active_logic() == out
    assert [p["status"] for p in s.proposals()] == ["applied", "pending"]
    assert s.list_feedback()[0]["status"] == "applied"


def test_apply_with_nothing_approved_raises(tmp_path, logic):
    import pytest
    s = Store(tmp_path)
    with pytest.raises(ValueError, match="Chưa có đề xuất"):
        apply_approved(s, logic)


def test_feedback_lesson_path(tmp_path, loaded, logic):
    s = Store(tmp_path)
    s.add_feedback({"unit_id": "pl:PL Alpha", "text": "hết stock"})
    out = propose_from_feedback(s.list_feedback()[0], {}, logic, s, loaded, date(2026, 10, 19),
                                ask_fn=lambda p, sc: {"kind": "lesson", "rationale": "r", "lesson_text": "Kiểm tra stock trước khi SCALE UP"})
    assert out["kind"] == "lesson"
    assert s.lessons()[0]["text"].startswith("Kiểm tra stock") and s.list_feedback()[0]["status"] == "lesson"


def test_feedback_param_path_backtested(tmp_path, loaded, logic):
    s = Store(tmp_path)
    s.add_feedback({"unit_id": "camp:x", "text": "SCALE UP quá dễ"})
    out = propose_from_feedback(s.list_feedback()[0], {}, logic, s, loaded, date(2026, 10, 19),
                                ask_fn=lambda p, sc: {"kind": "param", "param_key": "camp_good", "proposed_value": 0.5, "rationale": "r"})
    p = s.proposals()[0]
    assert out["kind"] == "param" and p["status"] == "pending" and p["old"] == 1.0 and p["new"] == 0.5
    assert p["backtest"]["removed"]["MED"] >= 1 and s.list_feedback()[0]["status"] == "proposed"


def test_feedback_invalid_param_becomes_rule(tmp_path, loaded, logic):
    s = Store(tmp_path)
    s.add_feedback({"unit_id": "pl:PL Alpha", "text": "x"})
    propose_from_feedback(s.list_feedback()[0], {}, logic, s, loaded, date(2026, 10, 19),
                          ask_fn=lambda p, sc: {"kind": "param", "param_key": "stock_floor", "proposed_value": 3, "rationale": "cần data tồn kho"})
    assert s.proposals()[0]["status"] == "saved_rule"


def test_review_proposals_dedupe(tmp_path, loaded, logic):
    s = Store(tmp_path)
    f = [{"severity": "MED", "title": "CUT bắt nhiều", "detail": "d", "kind": "param", "param_key": "camp_cut", "proposed_value": 1.25},
         {"severity": "MED", "title": "rule", "detail": "d", "kind": "rule"}]
    proposals_from_review(f, logic, s, loaded, date(2026, 10, 19))
    proposals_from_review(f, logic, s, loaded, date(2026, 10, 19))
    assert len(s.proposals()) == 1 and s.proposals()[0]["source"] == "review"

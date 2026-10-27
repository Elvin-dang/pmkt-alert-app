import json
from datetime import date

import pytest

from pmkt_alert.ai import fallback_slack, generate
from pmkt_alert.claude import ClaudeError
from pmkt_alert.pipeline import result_to_json, run_rules
from pmkt_alert.store import Store


@pytest.fixture(scope="module")
def result_json(loaded, logic):
    return result_to_json(run_rules(loaded, logic, date(2026, 10, 19)))


def _is(schema, key):
    return key in schema["properties"]


def test_generate_survives_failures(result_json, logic, tmp_path):
    def ask_fn(prompt, schema):
        if _is(schema, "findings"):
            return {"findings": []}
        if '"PIC A"' in prompt:
            raise ClaudeError("timeout")
        return {"insights": [], "todos": [], "slack": "ok"}
    g = generate(result_json, logic, Store(tmp_path), {}, "", ask_fn=ask_fn)
    assert g["claude_ok"] is False and g["error"] == "timeout"
    assert set(g["per_pic"]) == {d["pic"] for d in result_json["digest"]}
    assert g["per_pic"]["PIC A"]["slack"].startswith("Chào PIC A")  # rule-based fallback
    assert g["per_pic"]["PIC B"]["slack"] == "ok"


def test_ungrounded_items_dropped(result_json, logic, tmp_path):
    camp_id = next(r["unit_id"] for r in result_json["camp"] if r["pic"] == "PIC A")
    bad = {"insights": [{"text": "lỗ $123,456", "refs": [camp_id]}],
           "todos": [{"title": "Cắt", "detail": "dư chi $999,999", "severity": "HIGH", "due": "today", "refs": [camp_id]}],
           "slack": "tiêu $888,888"}
    g = generate(result_json, logic, Store(tmp_path), {}, "",
                 ask_fn=lambda p, s: {"findings": []} if _is(s, "findings") else bad)
    a = g["per_pic"]["PIC A"]
    assert a["todos"] == [] and a["insights"] == [] and a["dropped"] == 3
    assert a["slack"].startswith("Chào PIC A")


def test_review_unknown_param_downgraded(result_json, logic, tmp_path):
    findings = {"findings": [{"severity": "MED", "title": "a", "detail": "d", "kind": "param", "param_key": "camp_cut", "proposed_value": 1.25},
                             {"severity": "MED", "title": "b", "detail": "d", "kind": "param", "param_key": "nope", "proposed_value": 2},
                             {"severity": "MED", "title": "c", "detail": "d", "kind": "param", "param_key": "matrix:F|F|F", "proposed_value": "REVIEW ADS"}]}
    g = generate(result_json, logic, Store(tmp_path), {}, "",
                 ask_fn=lambda p, s: findings if _is(s, "findings") else {"insights": [], "todos": [], "slack": ""})
    assert [f["kind"] for f in g["review"]] == ["param", "rule", "param"] and g["claude_ok"] is True


def test_prompt_contains_style_lessons_and_rows(result_json, logic, tmp_path):
    s = Store(tmp_path)
    s.add_lesson("Kiểm tra stock trước khi SCALE UP", "x")
    s.save_style({"rules": "Luôn ghi số $"})
    seen = []
    generate(result_json, logic, s, {}, "DEFIND", ask_fn=lambda p, sc: seen.append(p) or (
        {"findings": []} if _is(sc, "findings") else {"insights": [], "todos": [], "slack": ""}))
    pic_a = next(p for p in seen if '"PIC A"' in p)
    assert "Kiểm tra stock" in pic_a and "Luôn ghi số $" in pic_a and "DEFIND" in pic_a and "camp:" in pic_a


def test_fallback_slack():
    d = {"pic": "PIC A", "pl_high": 7, "pl_med": 5, "pl_trend_review": 4, "camp_high": 5, "camp_med": 27, "camp_followup": 4, "excess_new": 615.72}
    assert fallback_slack(d, "2026-10-19") == ("Chào PIC A, báo cáo ngày 19/10 (L7D): 7 PL HIGH, 5 PL MED, 4 PL có trend cần review; "
                                              "32 campaign cần action mới (dư chi ~$616), 4 campaign đã action đang follow-up.")

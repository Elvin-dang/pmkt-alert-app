from datetime import date

import pytest

from pmkt_alert.ai import consistent, generate
from pmkt_alert.pipeline import result_to_json, run_rules
from pmkt_alert.store import Store


@pytest.fixture(scope="module")
def rj(loaded, logic):
    return result_to_json(run_rules(loaded, logic, date(2026, 10, 19)))


def test_consistent_with_rule_direction():
    down = {"unit_id": "pl:X", "pacing_action": "SCALE DOWN – overspend + TACoS vượt"}
    up = {"unit_id": "camp:1:X", "base_action": "SCALE UP – tăng bid/budget"}
    assert not consistent("Tăng bid cho PL X", [down])
    assert consistent("Giảm bid placement cho PL X", [down])
    assert not consistent("Pause camp này", [up]) and consistent("Tăng budget 20%", [up])
    assert consistent("Tăng bid", [down, up])  # mixed directions: not judged


def _is(schema, key):
    return key in schema["properties"]


def _alpha_camp(rj):
    return next(r for r in rj["camp"] if r["pic"] == "PIC A" and r["sev"] in ("HIGH", "MED"))


def test_careful_runs_critic_and_uses_its_output(rj, logic, tmp_path):
    camp = _alpha_camp(rj)
    draft = {"insights": [{"text": "nháp", "refs": [camp["unit_id"]]}], "todos": [], "slack": "nháp"}
    final = {"insights": [{"text": "bản đã biên tập", "refs": [camp["unit_id"]]}], "todos": [], "slack": "bản cuối"}
    prompts = []

    def ask_fn(p, s):
        prompts.append(p)
        if _is(s, "findings"):
            return {"findings": []}
        return final if "BIÊN TẬP" in p else draft
    g = generate(rj, logic, Store(tmp_path), {}, "", ask_fn=ask_fn, careful=True)
    a = g["per_pic"]["PIC A"]
    assert a["insights"][0]["text"] == "bản đã biên tập" and a["slack"] == "bản cuối" and a["steps"] == 5
    assert any("BIÊN TẬP" in p and "nháp" in p for p in prompts)


def test_critic_breaking_rules_falls_back_to_checked_draft(rj, logic, tmp_path):
    camp = _alpha_camp(rj)
    draft = {"insights": [{"text": "nháp đúng", "refs": [camp["unit_id"]]}], "todos": [], "slack": "ok"}
    bad = {"insights": [{"text": "lỗ $999,999", "refs": [camp["unit_id"]]}], "todos": [], "slack": "ok"}
    g = generate(rj, logic, Store(tmp_path), {}, "", careful=True,
                 ask_fn=lambda p, s: {"findings": []} if _is(s, "findings") else (bad if "BIÊN TẬP" in p else draft))
    assert g["per_pic"]["PIC A"]["insights"][0]["text"] == "nháp đúng"


def test_contradicting_todo_dropped(rj, logic, tmp_path):
    pl = next(r for r in rj["pl"] if r["pic"] == "PIC B" and r["pacing_action"].startswith("NO PLAN"))
    camp = next(r for r in rj["camp"] if r["pic"] == "PIC A" and r["base_action"].startswith("SCALE UP"))
    out = {"insights": [], "slack": "", "todos": [
        {"title": "Pause camp", "detail": "tắt luôn", "severity": "HIGH", "due": "today", "refs": [camp["unit_id"]]},
        {"title": "Tăng budget", "detail": "đẩy thêm", "severity": "MED", "due": "week", "refs": [camp["unit_id"]]}]}
    g = generate(rj, logic, Store(tmp_path), {}, "", careful=False,
                 ask_fn=lambda p, s: {"findings": []} if _is(s, "findings") else out)
    assert [t["title"] for t in g["per_pic"]["PIC A"]["todos"]] == ["Tăng budget"]


def test_prompt_has_comparisons(rj, logic, tmp_path):
    prompts = []
    s = Store(tmp_path)
    s.save_run({**rj, "as_of": "2026-10-12"}, None)  # an earlier run to compare with
    generate(rj, logic, s, {}, "", careful=False,
             ask_fn=lambda p, sc: prompts.append(p) or ({"findings": []} if _is(sc, "findings") else {"insights": [], "todos": [], "slack": ""}))
    pic_a = next(p for p in prompts if '"PIC A"' in p and "insights" in p)
    assert "Lần chạy trước (2026-10-12)" in pic_a and "Trung bình đội" in pic_a


def test_quick_mode_one_call_per_pic(rj, logic, tmp_path):
    n = {"c": 0}
    def ask_fn(p, s):
        n["c"] += 1
        return {"findings": []} if _is(s, "findings") else {"insights": [], "todos": [], "slack": ""}
    generate(rj, logic, Store(tmp_path), {}, "", ask_fn=ask_fn, careful=False)
    active = [d for d in rj["digest"] if any(d[k] for k in ("pl_high", "pl_med", "pl_trend_review", "camp_high", "camp_med", "camp_followup"))]
    assert n["c"] == len(active) + 1


def test_negated_advice_is_consistent():
    down = {"unit_id": "camp:1:X", "base_action": "CUT/OPTIMIZE – ACoS > PL avg"}
    assert consistent("Đừng tăng bid thêm, cắt bid 10%", [down])
    assert consistent("Không tăng budget cho camp này", [down])
    assert not consistent("Nên tăng bid 10%", [down])


def test_generate_reports_substeps_and_call_count(rj, logic, tmp_path):
    from pmkt_alert.ai import planned_calls
    events, calls = [], []
    draft = {"insights": [], "todos": [], "slack": "x"}
    g = generate(rj, logic, Store(tmp_path), {}, "", careful=True,
                 ask_fn=lambda p, s: calls.append(1) or ({"findings": []} if _is(s, "findings") else draft),
                 on_step=lambda *e: events.append(e))
    assert g["claude_ok"] and planned_calls(rj, careful=True) == len(calls)
    steps = {e[0] for e in events}
    assert {"pic:PIC A", "review"} <= steps
    a = [e for e in events if e[0] == "pic:PIC A"]
    assert a[0][1] == "running" and a[-1][1] == "done" and len(a) >= 3  # draft → critic → done
    assert sum(1 for e in events if e[3]) == len(calls)  # one "call finished" tick per Claude call

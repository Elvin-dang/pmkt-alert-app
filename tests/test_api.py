import json
from pathlib import Path

import pytest

from pmkt_alert.api import Api
from pmkt_alert.claude import ClaudeError, ClaudeStatus
from pmkt_alert.store import Store
from pmkt_alert.updater import Release
from pmkt_alert.xlsx import sheet_names


def empty_for(schema):
    props = schema["properties"]
    if "findings" in props:
        return {"findings": []}
    if "kind" in props:
        return {"kind": "lesson", "rationale": "r", "lesson_text": "L"}
    if "insights" in props:
        return {"insights": [], "todos": [], "slack": ""}
    return {"slack": "Chào PIC A"}


OK = lambda: ClaudeStatus(True, "2.1", True, True, 1.0, None)


def always_raise(exc):
    def f(*a, **k):
        raise exc
    return f


def paths(synthetic_paths):
    return [str(p) for p in synthetic_paths]


def test_run_without_claude(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("không chạy")))
    out = api.run(paths(synthetic_paths))
    assert "error" not in out and out["ai"]["claude_ok"] is False and out["result"]["digest"]
    assert out["result"]["inputs"]["activity"]["rows"] == 5
    assert api.history()["runs"][0]["run_id"] == out["run_id"]
    assert api.results()["run_id"] == out["run_id"]


def test_run_rule_only(tmp_path, synthetic_paths):
    out = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(AssertionError("must not call"))).run(paths(synthetic_paths), use_claude=False)
    assert out["ai"] is None and out["result"]["pl"]


def test_bad_input_returns_error_not_raise(tmp_path):
    out = Api(Store(tmp_path / "s"), status_fn=OK).run([str(tmp_path)])
    assert out["error"].startswith("Thiếu")


def test_detect(tmp_path, synthetic_paths):
    out = Api(Store(tmp_path / "s"), status_fn=OK).detect(paths(synthetic_paths))
    assert set(out["roles"]) == {"tracker", "ads", "activity", "logic", "defind"}
    assert out["roles"]["logic"]["name"] == "Alert_Logic_Ver 1.xlsx"


def test_feedback_roundtrip(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=lambda p, s: empty_for(s))
    run = api.run(paths(synthetic_paths))
    pl0 = run["result"]["pl"][0]
    out = api.submit_feedback({"unit_id": pl0["unit_id"], "issue": "Sai nhãn", "expected": "MAINTAIN", "text": "hết stock"})
    assert out["kind"] == "lesson" and api.lessons()["lessons"][0]["text"] == "L"
    fb = api.review()["feedback"][0]
    assert fb["row"]["unit_id"] == pl0["unit_id"] and fb["run_id"] == run["run_id"] and fb["logic_version"] == 1


def test_feedback_claude_down_keeps_feedback(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("down")))
    run = api.run(paths(synthetic_paths))
    out = api.submit_feedback({"unit_id": run["result"]["pl"][0]["unit_id"], "text": "x"})
    assert out["error"] and api.review()["feedback"][0]["status"] == "new"


def test_approve_and_apply_creates_ver2_and_reruns(tmp_path, synthetic_paths):
    finding = {"findings": [{"severity": "MED", "title": "t", "detail": "d", "kind": "param", "param_key": "camp_good", "proposed_value": 0.5}]}
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=lambda p, s: finding if "findings" in s["properties"] else empty_for(s))
    api.run(paths(synthetic_paths))
    prop = api.review()["proposals"][0]
    api.set_proposal(prop["id"], "approved")
    out = api.apply_proposals()
    assert out["result"]["logic_version"] == 2
    assert [v["version"] for v in api.history()["logic_versions"]] == [1, 2]


def test_export(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("x")))
    api.run(paths(synthetic_paths))
    out = api.export("PIC A", str(tmp_path / "a.xlsx"))
    assert sheet_names(Path(out["path"])) == ["Cảnh báo PL", "Cảnh báo Campaign", "To-do", "Insight", "Data"]


def test_check_update(tmp_path):
    s = Store(tmp_path)
    assert Api(s, release_fn=lambda *a, **k: None).check_update()["newer"] is False
    s.save_settings({"github_repo": "o/r"})
    rel = Release("v9.0.0", "## Mới", "2026-10-26", "u1", "u2")
    old = Release("v8.0.0", "## Cũ", "2026-10-01", "u3", "u4")
    out = Api(s, release_fn=lambda *a, **k: rel, recent_fn=lambda *a, **k: [rel, old]).check_update()
    assert out["newer"] is True and out["latest"] == "v9.0.0" and [p["tag"] for p in out["previous"]] == ["v8.0.0"]


def test_status_and_email_map(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("x")))
    assert api.claude_status()["level"] == "ok"
    api.run(paths(synthetic_paths))
    m = api.email_map_suggestions()["email_map"]
    assert set(m) == {"pica@example.com", "picb@example.com"}  # unmatched emails listed with "" to fill in


def test_all_public_methods_never_raise(tmp_path):
    api = Api(Store(tmp_path / "s"), status_fn=OK)
    for name in ["results", "review", "apply_proposals", "preview_style", "install_update"]:
        out = getattr(api, name)()
        assert isinstance(out, dict), name
    json.dumps(api.history())


def test_pick_folder_without_window(tmp_path):
    assert "error" in Api(Store(tmp_path), status_fn=OK).pick_folder()


def test_claude_not_ready_skips_ai_stage(tmp_path, synthetic_paths):
    bad = lambda: ClaudeStatus(True, "2.1", False, False, None, "Chưa đăng nhập Claude Code")
    api = Api(Store(tmp_path / "s"), status_fn=bad, ask_fn=always_raise(AssertionError("must not call")))
    out = api.run(paths(synthetic_paths))
    assert out["ai"]["claude_ok"] is False and out["ai"]["error"] == "Chưa đăng nhập Claude Code"
    assert out["ai"]["per_pic"]["PIC A"]["slack"].startswith("Chào PIC A")


def test_ai_saved_even_if_proposals_fail(tmp_path, synthetic_paths, monkeypatch):
    import pmkt_alert.api as api_mod
    monkeypatch.setattr(api_mod, "proposals_from_review", always_raise(RuntimeError("backtest boom")))
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=lambda p, s: empty_for(s))
    out = api.run(paths(synthetic_paths))
    assert "error" not in out and out["ai"]["claude_ok"] is True
    assert api.results(out["run_id"])["ai"]["claude_ok"] is True


def test_export_and_feedback_use_viewed_run(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=lambda p, s: empty_for(s))
    old = api.run(paths(synthetic_paths), as_of="2026-10-12")
    new = api.run(paths(synthetic_paths))
    assert old["run_id"] != new["run_id"]
    unit = old["result"]["pl"][0]["unit_id"]
    api.submit_feedback({"unit_id": unit, "text": "x", "run_id": old["run_id"]})
    fb = api.review()["feedback"][0]
    assert fb["run_id"] == old["run_id"] and fb["row"]["unit_id"] == unit
    out = api.export("PIC A", str(tmp_path / "a.xlsx"), old["run_id"])
    assert out["run_id"] == old["run_id"]


class FakeWindow:
    def __init__(self, picked=None):
        self.picked, self.js, self.dialogs = picked, [], []

    def create_file_dialog(self, dialog_type, **kw):
        self.dialogs.append((dialog_type, kw))
        return self.picked

    def evaluate_js(self, code):
        self.js.append(code)


def test_detect_partial_lists_missing(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK)
    two = [str(p) for p in synthetic_paths if p.name in ("ads.xlsx", "defind.xlsx")]
    out = api.detect(two)
    assert set(out["roles"]) == {"ads", "defind"} and set(out["missing"]) == {"tracker", "activity", "logic"}
    assert out["unknown"] == []


def test_detect_new_pick_replaces_same_role_and_flags_unknown(tmp_path, synthetic_paths):
    import shutil
    api = Api(Store(tmp_path / "s"), status_fn=OK)
    newer = tmp_path / "ads_new.xlsx"
    shutil.copy(next(p for p in synthetic_paths if p.name == "ads.xlsx"), newer)
    junk = tmp_path / "notes.xlsx"
    from factory import write_xlsx
    write_xlsx(junk, {"Sheet": [["a"], [1]]})
    out = api.detect([str(newer), str(junk)] + [str(p) for p in synthetic_paths])  # new picks first
    assert out["roles"]["ads"]["name"] == "ads_new.xlsx" and out["missing"] == []
    assert out["unknown"] == ["notes.xlsx"]


def test_pick_files_dialog(tmp_path):
    import webview
    api = Api(Store(tmp_path), status_fn=OK)
    api._window = FakeWindow(picked=("/a/x.xlsx", "/a/y.xlsx"))
    assert api.pick_files() == {"paths": ["/a/x.xlsx", "/a/y.xlsx"]}
    kind, kw = api._window.dialogs[0]
    assert kind == webview.FileDialog.OPEN and kw["allow_multiple"] is True and "*.xlsx" in kw["file_types"][0]
    api._window.picked = None
    assert api.pick_files() == {"paths": []}


def test_drop_handler_sends_full_paths_to_ui(tmp_path):
    api = Api(Store(tmp_path), status_fn=OK)
    api._window = FakeWindow()
    api._on_drop({"dataTransfer": {"files": [{"name": "a.xlsx", "pywebviewFullPath": "/d/a.xlsx"},
                                              {"name": "b.txt"}]}})
    assert api._window.js == ['window.onDropPaths && onDropPaths(["/d/a.xlsx"])']


def test_install_claude_reports_status(tmp_path, monkeypatch):
    import pmkt_alert.api as api_mod
    monkeypatch.setattr(api_mod, "install_claude_cli", lambda: {"ok": True, "output": "installed"})
    api = Api(Store(tmp_path), status_fn=lambda: ClaudeStatus(True, "2.1", False, False, None, "Chưa đăng nhập Claude Code"))
    out = api.install_claude()
    assert out["ok"] is True and out["status"]["installed"] is True and out["status"]["logged_in"] is False


def test_open_login_requires_installed(tmp_path, monkeypatch):
    import pmkt_alert.api as api_mod
    monkeypatch.setattr(api_mod, "claude_exe", lambda: None)
    assert "error" in Api(Store(tmp_path), status_fn=OK).open_claude_login()
    launched = []
    monkeypatch.setattr(api_mod, "claude_exe", lambda: "/x/claude")
    monkeypatch.setattr(api_mod, "open_login", lambda exe: launched.append(exe))
    assert Api(Store(tmp_path), status_fn=OK).open_claude_login() == {"ok": True} and launched == ["/x/claude"]


def test_bad_claude_status_is_not_an_api_error(tmp_path):
    s = Api(Store(tmp_path), status_fn=lambda: ClaudeStatus(False, None, False, False, None, "Chưa cài Claude Code")).claude_status()
    assert "error" not in s and s["detail"] == "Chưa cài Claude Code" and s["level"] == "bad"


def test_rewrite_message_uses_pic_address_and_saves(tmp_path, synthetic_paths):
    seen = []
    def ask_fn(p, s):
        seen.append(p)
        if "slack" in s["properties"] and "insights" not in s["properties"]:
            return {"slack": "Chào chị Tâm, hôm nay có việc HIGH nha"}
        return empty_for(s)
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=ask_fn)
    run = api.run(paths(synthetic_paths))
    api.save_pic_address("PIC A", {"self": "em", "call": "chị", "name": "Tâm"})
    out = api.rewrite_message("PIC A", run["run_id"])
    assert out["slack"] == "Chào chị Tâm, hôm nay có việc HIGH nha"
    assert 'gọi PIC là "chị Tâm"' in seen[-1]
    assert api.results(run["run_id"])["ai"]["per_pic"]["PIC A"]["slack"] == out["slack"]


def test_rewrite_message_rejects_made_up_numbers(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK,
              ask_fn=lambda p, s: {"slack": "dư chi $987,654"} if "insights" not in s["properties"] and "slack" in s["properties"] else empty_for(s))
    run = api.run(paths(synthetic_paths))
    before = api.results(run["run_id"])["ai"]["per_pic"]["PIC A"]["slack"]
    out = api.rewrite_message("PIC A", run["run_id"])
    assert "error" in out and api.results(run["run_id"])["ai"]["per_pic"]["PIC A"]["slack"] == before


def test_evidence_endpoint(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("x")))
    run = api.run(paths(synthetic_paths))
    ev = api.evidence("pl:PL Alpha", run["run_id"])
    assert ev["unit_id"] == "pl:PL Alpha" and ev["sections"][0]["source"].endswith("Product Info")
    assert ev["files"]["tracker"] == "tracker.xlsx" and ev["logic_file"] == "Alert_Logic_Ver 1.xlsx"
    assert "error" in api.evidence("pl:Nope", run["run_id"])
    import json
    json.dumps(ev, allow_nan=False)


def test_dashboard_and_team_review(tmp_path, synthetic_paths):
    review = {"summary": "PIC A dẫn đầu", "highlights": [{"pic": "PIC A", "metric": "gmv_pace", "text": "PIC A tốt"}],
              "improve": [{"pic": "PIC B", "metric": "tacos_ratio", "text": "TACoS cao", "suggestion": "Giảm bid"}]}
    def ask_fn(p, s):
        if "highlights" in s["properties"]:
            return review
        return empty_for(s)
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=ask_fn)
    run = api.run(paths(synthetic_paths))
    d = api.dashboard(run["run_id"])
    assert {p["pic"] for p in d["scorecard"]["pics"]} >= {"PIC A", "PIC B"} and d["weekly"] and d["runs"]
    assert d["team_review"] is None
    out = api.team_review(run["run_id"])
    assert out["summary"] == "PIC A dẫn đầu" and api.dashboard(run["run_id"])["team_review"]["summary"] == "PIC A dẫn đầu"
    api.save_score_weights({"gmv_pace": 2})
    assert api.dashboard(run["run_id"])["scorecard"]["weights"]["gmv_pace"] == 2


def test_team_review_drops_made_up_numbers(tmp_path, synthetic_paths):
    bad = {"summary": "Tổng GMV $123,456,789", "highlights": [], "improve": []}
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=lambda p, s: bad if "highlights" in s["properties"] else empty_for(s))
    run = api.run(paths(synthetic_paths))
    out = api.team_review(run["run_id"])
    assert out["summary"] == "" and out["dropped"] == 1


def test_careful_mode_setting_controls_critic(tmp_path, synthetic_paths):
    calls = []
    def ask_fn(p, s):
        calls.append("critic" if "BIÊN TẬP" in p else "other")
        return empty_for(s)
    st = Store(tmp_path / "s")
    assert st.get_settings()["careful_mode"] is True
    api = Api(st, status_fn=OK, ask_fn=ask_fn)
    api.run(paths(synthetic_paths))
    assert "critic" in calls
    calls.clear()
    st.save_settings({"careful_mode": False})
    api.run(paths(synthetic_paths))
    assert "critic" not in calls and calls


def test_claude_note_reaches_every_prompt(tmp_path, synthetic_paths):
    prompts = []
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=lambda p, s: prompts.append(p) or empty_for(s))
    api.save_settings({"claude_note": "Không bao giờ đề xuất pause camp Brand."})
    api.run(paths(synthetic_paths))
    assert prompts and all("Không bao giờ đề xuất pause camp Brand." in p for p in prompts)
    assert all(p.index("GHI CHÚ") < 200 for p in prompts)


def test_memory_info_and_prune(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("x")))
    api.run(paths(synthetic_paths))
    info = api.memory_info()
    assert info["runs"] == 1 and info["limit_bytes"] == 1024 ** 3 and info["oldest"]["date"]
    assert api.prune_memory()["deleted"] == []


def test_picked_logic_file_is_used_even_with_other_name(tmp_path, synthetic_paths):
    import shutil
    from factory import make_logic
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("x")))
    first = api.run(paths(synthetic_paths))
    assert first["result"]["logic_version"] == 1
    d = tmp_path / "other"
    d.mkdir()
    for p in synthetic_paths:
        if "Alert_Logic" not in p.name:
            shutil.copy(p, d / p.name)
    team = make_logic(d / "Alert_Logic_System_Team_v3.xlsx")
    import openpyxl
    wb = openpyxl.load_workbook(team)
    for row in wb["Config"].iter_rows(min_col=2, max_col=3):
        if row[0].value and str(row[0].value).startswith("Sàn click tối thiểu"):
            row[1].value = 99
    wb.save(team)
    out = api.run([str(d)])
    assert out["result"]["logic_version"] == 3
    assert all(c["min_clicks"] >= 99 for c in out["result"]["camp"])
    again = api.run([str(d)])  # same file again: no duplicate import, still v3
    assert again["result"]["logic_version"] == 3 and len(api.history()["logic_versions"]) == 2


def _with_v3(tmp_path, synthetic_paths, **kw):
    import shutil
    from factory import make_logic_v3
    d = tmp_path / "v3"
    d.mkdir()
    for p in synthetic_paths:
        if "Alert_Logic" not in p.name:
            shutil.copy(p, d / p.name)
    make_logic_v3(d / "Alert_Logic_System_Team_v3.xlsx", **kw)
    return d


def test_run_completes_with_broken_logic_and_reports(tmp_path, synthetic_paths):
    d = _with_v3(tmp_path, synthetic_paths, blank="Sàn click tối thiểu")
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=always_raise(ClaudeError("x")))
    out = api.run([str(d)])
    assert "error" not in out and out["result"]["logic_version"] == 3 and out["result"]["pl"]
    codes = {(i["code"], i["key"]) for i in out["result"]["logic_issues"]}
    assert ("BLANK", "min_clicks") in codes and out["result"]["model"] == "score_v3"
    assert not any(c == "MISSING" for c, _ in codes)  # Ver 1 pacing keys are not part of the score model
    ev = out["ai"]["logic_eval"]  # no Claude: rule-based verdicts so nothing is lost
    assert ev["by_claude"] is False and any(x["verdict"] == "change" for x in ev["items"])


def test_claude_evaluates_logic_issues(tmp_path, synthetic_paths):
    d = _with_v3(tmp_path, synthetic_paths, blank="Sàn click tối thiểu")
    def ask_fn(p, s):
        if "verdict_items" in s["properties"]:
            return {"summary": "File dùng mô hình chấm điểm mới", "verdict_items": [
                {"ref": 0, "verdict": "critical", "reason": "Sàn click trống", "fix": "Điền 15 vào ô", "suggested_value": "15"},
                {"ref": 999, "verdict": "ignore", "reason": "x", "fix": "", "suggested_value": None}]}
        return empty_for(s)
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=ask_fn)
    out = api.run([str(d)])
    ev = out["ai"]["logic_eval"]
    assert ev["by_claude"] is True and ev["summary"].startswith("File dùng")
    crit = [x for x in ev["items"] if x["verdict"] == "critical"]
    assert len(crit) == 1 and crit[0]["issue"]["key"] == out["result"]["logic_issues"][0]["key"]
    assert all(x["issue"] for x in ev["items"])  # unknown refs dropped


def test_whats_new_shows_once_per_version(tmp_path, monkeypatch):
    import pmkt_alert.api as api_mod
    monkeypatch.setattr(api_mod, "__version__", "0.1.6")
    api = Api(Store(tmp_path), status_fn=OK)
    w = api.whats_new()
    assert w["version"] == "0.1.6" and w["show"] is True and "terminal" in w["notes"] and w["previous"]
    api.mark_whats_new_seen()
    assert api.whats_new()["show"] is False


def test_whats_new_hidden_in_dev(tmp_path, monkeypatch):
    import pmkt_alert.api as api_mod
    monkeypatch.setattr(api_mod, "__version__", "0.0.0-dev")
    assert Api(Store(tmp_path), status_fn=OK).whats_new()["show"] is False


def test_stop_during_claude_keeps_rule_results(tmp_path, synthetic_paths):
    import threading
    started = threading.Event()
    calls = []

    def ask_fn(p, s):
        calls.append(1)
        started.set()
        for _ in range(100):  # a slow Claude call
            if api._cancel.is_set():
                raise ClaudeError("Đã dừng theo yêu cầu", retryable=False)
            threading.Event().wait(0.05)
        return empty_for(s)
    api = Api(Store(tmp_path / "s"), status_fn=OK, ask_fn=ask_fn)
    box = {}
    t = threading.Thread(target=lambda: box.update(out=api.run(paths(synthetic_paths))))
    t.start()
    started.wait(10)
    assert api.cancel_run()["ok"] is True
    t.join(20)
    out = box["out"]
    assert out["result"]["pl"] and out["ai"]["claude_ok"] is False and "dừng" in out["ai"]["error"].lower()
    assert out["stopped"] is True and len(calls) <= 5
    assert api.results(out["run_id"])["ai"]["error"]  # saved


def test_stop_before_rules_cancels(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), status_fn=OK)
    api._cancel.set()  # stop pressed while files were loading
    out = api.run(paths(synthetic_paths))
    assert out == {"cancelled": True} and api.history()["runs"] == []


def test_detect_csv_tables_fill_tracker_slot(tmp_path):
    from factory import make_all_csv
    files = make_all_csv(tmp_path / "c")
    api = Api(Store(tmp_path / "s"), status_fn=OK)
    out = api.detect([str(files["raw"]), str(files["products"]), str(files["ads"])])
    assert out["roles"]["ads"]["name"] == "ads_camp.csv"
    assert "tracker" in out["missing"] and "KPI" in out["tracker_missing"]
    full = api.detect([str(tmp_path / "c")])
    t = full["roles"]["tracker"]
    assert full["missing"] == [] and set(t["paths"]) == {str(files[k]) for k in ("raw", "products", "kpi")}
    assert "raw_sso_us.csv" in t["name"]
    run = Api(Store(tmp_path / "s2"), status_fn=OK, ask_fn=always_raise(ClaudeError("x"))).run(
        [p for r in full["roles"].values() for p in r.get("paths", [r["path"]])])
    assert "error" not in run and run["result"]["pl"]


def test_progress_sends_eta_and_learns_step_times(tmp_path, synthetic_paths):
    class Win:
        calls = []
        def evaluate_js(self, js):
            self.calls.append(js)
    api = Api(Store(tmp_path / "s"), status_fn=OK,
              ask_fn=lambda p, s: {"findings": []} if "findings" in s["properties"] else {"insights": [], "todos": [], "slack": "x"})
    api._window = Win()
    out = api.run(paths(synthetic_paths))
    assert "error" not in out
    events = [json.loads("[" + js[js.index("onProgress(") + 11:-1] + "]") for js in Win.calls]
    assert all(len(e) == 4 and e[3]["eta"] >= 0 for e in events)
    assert any(e[0].startswith("pic:") for e in events) and events[-1][3]["eta"] == 0
    learned = api._store.get_settings()["step_times"]
    assert {"load", "rules", "claude_call"} <= set(learned)


def test_input_files_have_modified_time_and_detail(tmp_path, synthetic_paths):
    import os
    from datetime import datetime
    api = Api(Store(tmp_path / "s"), status_fn=OK)
    tracker = next(p for p in synthetic_paths if p.name == "tracker.xlsx")
    os.utime(tracker, (datetime(2026, 10, 27, 14, 5).timestamp(),) * 2)
    roles = api.detect([str(p) for p in synthetic_paths])["roles"]
    assert roles["tracker"]["modified"] == "2026-10-27T14:05:00"
    d = api.file_detail([roles["tracker"]["path"]])
    f = d["files"][0]
    assert f["name"] == "tracker.xlsx" and f["modified"] == "2026-10-27T14:05:00" and f["size"] > 0
    raw = next(s for s in f["sheets"] if s["name"] == "raw_sso_us")
    assert raw["rows"] > 0 and "ordered_gmv_usd" in raw["columns"] and len(raw["preview"]) <= 8
    assert raw["dates"]["column"] and raw["dates"]["min"] <= raw["dates"]["max"]
    json.dumps(d, allow_nan=False)
    csv = tmp_path / "ads.csv"
    csv.write_text("report_date,campaign_id,spend_usd\n2026-10-01,1,2.5\n2026-10-02,1,3\n", encoding="utf-8")
    c = api.file_detail([str(csv)])["files"][0]
    assert c["sheets"][0]["rows"] == 2 and c["sheets"][0]["dates"]["max"] == "2026-10-02"
    vn = tmp_path / "vn.csv"
    vn.write_text("Ngày,spend\n02/10/2026,1\n25/10/2026,2\n", encoding="utf-8")
    assert api.file_detail([str(vn)])["files"][0]["sheets"][0]["dates"] == {"column": "Ngày", "min": "2026-10-02", "max": "2026-10-25"}
    assert "error" in api.file_detail([str(tmp_path / "nope.xlsx")])

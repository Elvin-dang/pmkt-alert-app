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

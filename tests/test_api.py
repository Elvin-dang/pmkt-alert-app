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


def always_raise(exc):
    def f(*a, **k):
        raise exc
    return f


def paths(synthetic_paths):
    return [str(p) for p in synthetic_paths]


def test_run_without_claude(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), ask_fn=always_raise(ClaudeError("không chạy")))
    out = api.run(paths(synthetic_paths))
    assert "error" not in out and out["ai"]["claude_ok"] is False and out["result"]["digest"]
    assert out["result"]["inputs"]["activity"]["rows"] == 5
    assert api.history()["runs"][0]["run_id"] == out["run_id"]
    assert api.results()["run_id"] == out["run_id"]


def test_run_rule_only(tmp_path, synthetic_paths):
    out = Api(Store(tmp_path / "s"), ask_fn=always_raise(AssertionError("must not call"))).run(paths(synthetic_paths), use_claude=False)
    assert out["ai"] is None and out["result"]["pl"]


def test_bad_input_returns_error_not_raise(tmp_path):
    out = Api(Store(tmp_path / "s")).run([str(tmp_path)])
    assert out["error"].startswith("Thiếu")


def test_detect(tmp_path, synthetic_paths):
    out = Api(Store(tmp_path / "s")).detect(paths(synthetic_paths))
    assert set(out["roles"]) == {"tracker", "ads", "activity", "logic", "defind"}
    assert out["roles"]["logic"]["name"] == "Alert_Logic_Ver 1.xlsx"


def test_feedback_roundtrip(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), ask_fn=lambda p, s: empty_for(s))
    run = api.run(paths(synthetic_paths))
    pl0 = run["result"]["pl"][0]
    out = api.submit_feedback({"unit_id": pl0["unit_id"], "issue": "Sai nhãn", "expected": "MAINTAIN", "text": "hết stock"})
    assert out["kind"] == "lesson" and api.lessons()["lessons"][0]["text"] == "L"
    fb = api.review()["feedback"][0]
    assert fb["row"]["unit_id"] == pl0["unit_id"] and fb["run_id"] == run["run_id"] and fb["logic_version"] == 1


def test_feedback_claude_down_keeps_feedback(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), ask_fn=always_raise(ClaudeError("down")))
    run = api.run(paths(synthetic_paths))
    out = api.submit_feedback({"unit_id": run["result"]["pl"][0]["unit_id"], "text": "x"})
    assert out["error"] and api.review()["feedback"][0]["status"] == "new"


def test_approve_and_apply_creates_ver2_and_reruns(tmp_path, synthetic_paths):
    finding = {"findings": [{"severity": "MED", "title": "t", "detail": "d", "kind": "param", "param_key": "camp_good", "proposed_value": 0.5}]}
    api = Api(Store(tmp_path / "s"), ask_fn=lambda p, s: finding if "findings" in s["properties"] else empty_for(s))
    api.run(paths(synthetic_paths))
    prop = api.review()["proposals"][0]
    api.set_proposal(prop["id"], "approved")
    out = api.apply_proposals()
    assert out["result"]["logic_version"] == 2
    assert [v["version"] for v in api.history()["logic_versions"]] == [1, 2]


def test_export(tmp_path, synthetic_paths):
    api = Api(Store(tmp_path / "s"), ask_fn=always_raise(ClaudeError("x")))
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
    api = Api(Store(tmp_path / "s"), ask_fn=always_raise(ClaudeError("x")),
              status_fn=lambda: ClaudeStatus(True, "2.1", True, True, 1.0, None))
    assert api.claude_status()["level"] == "ok"
    api.run(paths(synthetic_paths))
    m = api.email_map_suggestions()["email_map"]
    assert set(m) == {"pica@example.com", "picb@example.com"}  # unmatched emails listed with "" to fill in


def test_all_public_methods_never_raise(tmp_path):
    api = Api(Store(tmp_path / "s"))
    for name in ["results", "review", "apply_proposals", "preview_style", "install_update"]:
        out = getattr(api, name)()
        assert isinstance(out, dict), name
    json.dumps(api.history())

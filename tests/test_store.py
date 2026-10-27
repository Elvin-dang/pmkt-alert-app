import sys

from factory import make_logic
from pmkt_alert.store import Store, default_base


def test_corrupt_file_recovers(tmp_path):
    s = Store(tmp_path)
    (tmp_path / "settings.json").write_text("{oops")
    assert s.get_settings()["auto_update_check"] is True
    assert list(tmp_path.glob("settings.json.corrupt-*"))


def test_settings_merge_defaults(tmp_path):
    s = Store(tmp_path)
    s.save_settings({"github_repo": "o/r"})
    assert s.get_settings()["github_repo"] == "o/r" and s.get_settings()["email_map"] == {}


def test_runs_roundtrip(tmp_path):
    s = Store(tmp_path)
    rid = s.save_run({"as_of": "2026-10-19", "logic_version": 1, "pl": [{"pacing_sev": "HIGH"}, {"pacing_sev": "LOW"}],
                      "camp": [{"sev": "MED"}]}, None)
    s.update_run_ai(rid, {"claude_ok": True})
    assert s.load_run(rid)["ai"] == {"claude_ok": True}
    s.add_feedback({"run_id": rid, "unit_id": "pl:X", "text": "sai"})
    runs = s.list_runs()
    assert runs[0]["run_id"] == rid and runs[0]["alert_count"] == 2 and runs[0]["feedback_count"] == 1


def test_feedback_lessons_style_proposals(tmp_path):
    s = Store(tmp_path)
    fid = s.add_feedback({"unit_id": "pl:X", "text": "sai"})
    assert s.list_feedback("new")[0]["id"] == fid
    s.set_feedback_status(fid, "lesson")
    assert s.list_feedback("new") == [] and s.list_feedback("lesson")[0]["id"] == fid
    lid = s.add_lesson("Kiểm tra stock", "feedback:" + fid)
    assert s.lessons()[0]["text"] == "Kiểm tra stock"
    s.delete_lesson(lid)
    assert s.lessons() == []
    assert s.get_style()["pronoun"] == "em_anhchi"
    s.add_style_sample("Toni ơi, check giúp em nha")
    assert s.get_style()["samples"] == ["Toni ơi, check giúp em nha"]
    s.save_proposals([{"id": "p1", "status": "pending"}])
    s.set_proposal_status("p1", "approved")
    assert s.proposals()[0]["status"] == "approved"


def test_logic_versions_and_active(tmp_path):
    s = Store(tmp_path / "s")
    s.import_logic(make_logic(tmp_path / "Alert_Logic_Ver 1.xlsx"))
    s.import_logic(make_logic(tmp_path / "Alert_Logic_Ver 2.xlsx"))
    assert [v for v, _ in s.logic_versions()] == [1, 2]
    assert s.active_logic().name == "Alert_Logic_Ver 2.xlsx"  # newest import becomes active
    s.set_active_logic(1)
    assert s.active_logic().name == "Alert_Logic_Ver 1.xlsx"


def test_default_base_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    assert str(default_base()).endswith("PMKT Alert")


def test_concurrent_settings_writes_keep_all_keys(tmp_path):
    import threading
    s = Store(tmp_path)
    threads = [threading.Thread(target=s.save_settings, args=({f"k{i}": i},)) for i in range(30)]
    [t.start() for t in threads]; [t.join() for t in threads]
    got = s.get_settings()
    assert all(got[f"k{i}"] == i for i in range(30)) and not list(tmp_path.glob("*.corrupt-*"))

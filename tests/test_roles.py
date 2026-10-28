import json
import re

import pytest

from pmkt_alert.api import Api
from pmkt_alert.claude import ClaudeError, ClaudeStatus
from pmkt_alert.store import Store

OK = lambda: ClaudeStatus(True, "2.1", True, True, 1.0, None)  # noqa: E731


def no_claude(*a, **k):
    raise ClaudeError("x")


def member(tmp_path, name, setup):
    m = Api(Store(tmp_path / name), status_fn=OK, ask_fn=no_claude)
    return m, m.setup_member(setup)["member_code"]


@pytest.fixture()
def team(tmp_path, synthetic_paths):
    share = tmp_path / "share"
    lead = Api(Store(tmp_path / "lead"), status_fn=OK, ask_fn=no_claude)
    setup = lead.setup_lead({"type": "folder", "folder": str(share)}, "Lead PMKT")["setup_code"]
    a, code_a = member(tmp_path, "a", setup)
    b, code_b = member(tmp_path, "b", setup)
    assert "error" not in lead.add_member(code_a, "PIC A", "Thành viên A")
    assert "error" not in lead.add_member(code_b, "PIC B", "Thành viên B")
    run = lead.run([str(p) for p in synthetic_paths])
    return {"lead": lead, "a": a, "b": b, "code_a": code_a, "run": run, "share": share, "setup": setup}


def test_no_auto_publish_then_manual_upload(team):
    assert team["run"]["published"] is None and not list(team["share"].glob("*.pmkt"))
    up = team["lead"].upload_report(team["run"]["run_id"])
    assert re.fullmatch(r"PMKT-Alert_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(-\d{2})?\.pmkt", up["name"])
    assert up["readers"] == {"PIC A": 1, "PIC B": 1} and "Chưa có PIC" in up["no_readers"]
    again = team["lead"].upload_report(team["run"]["run_id"])
    assert again["name"] != up["name"]  # never overwrites


def test_members_see_only_their_pic(team):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    a = team["a"]
    assert [r["name"] for r in a.list_reports()["reports"]] == [name]
    res = a.open_report(name)
    assert {r["pic"] for r in res["result"]["pl"]} == {"PIC A"} and {r["pic"] for r in res["result"]["camp"]} <= {"PIC A"}
    assert [d["pic"] for d in res["result"]["digest"]] == ["PIC A"] and list(res["ai"]["per_pic"]) == ["PIC A"]
    assert res["ai"]["review"] == [] and res["result"]["issues"] == [] and res.get("team_review") is None
    ev = a.evidence("pl:PL Alpha")
    assert "error" not in ev and all(r.get("asin") in ("B000000001", "B000000002") for r in ev["sections"][2]["rows"])
    assert "error" in a.evidence("pl:PL Gamma")  # PIC B's line
    db = a.dashboard()
    assert [p["pic"] for p in db["scorecard"]["pics"]] == ["PIC A"] and {w["pic"] for w in db["weekly"]} == {"PIC A"}
    full = next(p for p in team["lead"].dashboard()["scorecard"]["pics"] if p["pic"] == "PIC A")
    assert db["scorecard"]["pics"][0]["total"] == full["total"] and db["scorecard"]["pics"][0]["rank"] is None
    assert [d["pic"] for d in team["b"].open_report(name)["result"]["digest"]] == ["PIC B"]
    json.dumps(res, allow_nan=False)


def test_lead_can_open_its_upload_fully(team):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    assert {d["pic"] for d in team["lead"].open_report(name)["result"]["digest"]} >= {"PIC A", "PIC B"}


def test_removed_or_unregistered_member(team, tmp_path):
    lead = team["lead"]
    old = lead.upload_report(team["run"]["run_id"])["name"]
    stranger, _ = member(tmp_path, "c", team["setup"])
    assert "không có phần" in stranger.open_report(old)["error"]
    lead.remove_member(team["code_a"])
    new = lead.upload_report(team["run"]["run_id"])["name"]
    assert "không có phần" in team["a"].open_report(new)["error"] and "error" not in team["a"].open_report(old)


def test_bad_codes(team, tmp_path):
    assert "error" in team["lead"].add_member("PMKM-AAAAA", "PIC A", "x")
    assert "error" in Api(Store(tmp_path / "z"), status_fn=OK).setup_member("PMKT1:garbage")


@pytest.mark.parametrize("call", [
    lambda m: m.run([]), lambda m: m.export("PIC A", "/tmp/x.xlsx"), lambda m: m.save_style({}),
    lambda m: m.save_settings({"claude_note": "x"}), lambda m: m.apply_proposals(), lambda m: m.rewrite_message("PIC A"),
    lambda m: m.set_active_logic(1), lambda m: m.team_review(), lambda m: m.submit_feedback({"unit_id": "pl:PL Alpha"}),
    lambda m: m.upload_report(None), lambda m: m.add_member("PMKM-X", "PIC A", "x"), lambda m: m.delete_report("x.pmkt"),
])
def test_member_cannot_do_lead_actions(team, call):
    assert "Lead" in call(team["a"])["error"]


def test_member_settings_allowed_keys(team):
    assert "error" not in team["a"].save_settings({"language": "en"})


def test_transfer_lead(team, tmp_path):
    key_file = tmp_path / "lead.pmktkey"
    assert "error" not in team["lead"].export_lead_key(str(key_file), "chuyen quyen 123")
    new = Api(Store(tmp_path / "new"), status_fn=OK, ask_fn=no_claude)
    out = new.import_lead_key(str(key_file), "chuyen quyen 123")
    assert out["setup_code"] == team["setup"] and len(new.members()["members"]) == 2
    assert "error" in Api(Store(tmp_path / "bad"), status_fn=OK).import_lead_key(str(key_file), "sai")


def test_startup_file_open(team):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    a = team["a"]
    a._startup_file = str(team["share"] / name)
    assert a.startup_open()["opened"]["file"] == name and a.startup_open() == {"opened": None}


def test_register_file_type_commands():
    from pmkt_alert.app import file_type_entries
    e = file_type_entries(r"C:\Apps\PMKT-Alert.exe")
    assert (r"Software\Classes\.pmkt", "", "PMKTAlert.Run") in e
    assert (r"Software\Classes\PMKTAlert.Run\shell\open\command", "", '"C:\\Apps\\PMKT-Alert.exe" "%1"') in e


def test_supabase_login_stores_refresh_token(tmp_path, monkeypatch):
    import pmkt_alert.api as api_mod

    class FakeSB:
        token = None

        def login(self, email, pw):
            return "AT", "RT"
    monkeypatch.setattr(api_mod, "make_transport", lambda cfg, token=None: FakeSB())
    lead = Api(Store(tmp_path / "l"), status_fn=OK)
    lead.setup_lead({"type": "supabase", "url": "https://p.supabase.co", "anon": "ANON"}, "Lead")
    assert lead.lead_login("lead@example.com", "pw")["ok"] is True and lead._secrets()["sb_refresh"] == "RT"
    assert "LEAD_EMAIL" not in lead.supabase_sql()["sql"] and "lead@example.com" in lead.supabase_sql()["sql"]

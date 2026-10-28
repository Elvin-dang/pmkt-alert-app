import json
import re

import pytest

from fake_supabase import LEAD_PASSWORD, FakeSupabase
from pmkt_alert.api import Api
from pmkt_alert.claude import ClaudeError, ClaudeStatus
from pmkt_alert.store import Store
from pmkt_alert.supabase import pic_file

OK = lambda: ClaudeStatus(True, "2.1", True, True, 1.0, None)  # noqa: E731
LEAD = "lead@team.test"
URL, ANON = "https://p.supabase.co", "ANON"


def no_claude(*a, **k):
    raise ClaudeError("x")


def device(tmp_path, name, sb):
    return Api(Store(tmp_path / name), status_fn=OK, ask_fn=no_claude, sb_opener=sb)


def sign_in(api, email, password):
    assert "error" not in api.team_connect(URL, ANON)
    return api.team_sign_in(email, password)


@pytest.fixture()
def team(tmp_path, synthetic_paths):
    sb = FakeSupabase(LEAD)
    lead = device(tmp_path, "lead", sb)
    info = sign_in(lead, LEAD, LEAD_PASSWORD)
    assert info["role"] == "lead" and info["signed_in"]
    pw_a = lead.add_member("A@Team.test", "Thành viên A", "PIC A")["password"]  # stored lower-case
    pw_b = lead.add_member("b@team.test", "Thành viên B", "PIC B")["password"]
    assert len(pw_a) >= 12 and pw_a != pw_b
    a, b = device(tmp_path, "a", sb), device(tmp_path, "b", sb)
    assert sign_in(a, "a@team.test", pw_a)["role"] == "member" and sign_in(b, "b@team.test", pw_b)["pic"] == "PIC B"
    run = lead.run([str(p) for p in synthetic_paths])
    return {"sb": sb, "lead": lead, "a": a, "b": b, "run": run, "tmp": tmp_path, "pw_a": pw_a}


def test_wrong_password_or_unknown_email(team):
    stranger = device(team["tmp"], "s", team["sb"])
    assert "Sai email hoặc mật khẩu" in sign_in(stranger, "x@else.test", "whatever-123")["error"]
    assert "Sai email hoặc mật khẩu" in sign_in(stranger, "a@team.test", "wrong-password")["error"]


def test_lead_creates_and_manages_pic_accounts(team):
    lead, sb = team["lead"], team["sb"]
    rows = {m["email"]: m for m in lead.members()["members"]}
    assert rows["a@team.test"]["pic"] == "PIC A" and rows["a@team.test"]["status"] == "ready"
    pw = lead.add_member("c@team.test", "C", "PIC A")["password"]
    assert {m["email"]: m["status"] for m in lead.members()["members"]}["c@team.test"] == "invited"
    assert "error" not in lead.update_member("c@team.test", {"pic": "PIC B", "name": "C2"})
    assert sb.members["c@team.test"]["pic"] == "PIC B" and sb.passwords["c@team.test"] == pw
    assert "error" in lead.add_member("not-an-email", "x", "PIC A")
    assert "error" in lead.add_member("c@team.test", "dup", "PIC A")
    assert "error" in lead.add_member("d@team.test", "no pic", "")
    assert "error" not in lead.add_member("lead2@team.test", "Lead 2", "", role="lead")


def test_reset_password(team):
    new = team["lead"].reset_password("a@team.test")["password"]
    other = device(team["tmp"], "a3", team["sb"])
    assert "error" in sign_in(other, "a@team.test", team["pw_a"])
    assert sign_in(other, "a@team.test", new)["role"] == "member"


def test_user_changes_own_password(team):
    a = team["a"]
    assert "error" in a.team_change_password("short")
    assert "error" not in a.team_change_password("my-own-password-1")
    other = device(team["tmp"], "a4", team["sb"])
    assert sign_in(other, "a@team.test", "my-own-password-1")["signed_in"]


def test_lead_cannot_lock_or_delete_self(team):
    assert "error" in team["lead"].update_member(LEAD, {"active": False})
    assert "error" in team["lead"].remove_member(LEAD)


def test_no_auto_upload_then_manual_upload_never_overwrites(team):
    assert team["run"]["published"] is None and not team["sb"].objects
    up = team["lead"].upload_report(team["run"]["run_id"])
    assert re.fullmatch(r"PMKT-Alert_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(-\d{2})?", up["name"])
    assert up["readers"] == {"PIC A": 1, "PIC B": 1} and "Chưa có PIC" in up["no_readers"]
    assert set(team["sb"].objects) == {f"{up['name']}/lead.pmkt", f"{up['name']}/{pic_file('PIC A')}",
                                       f"{up['name']}/{pic_file('PIC B')}"}
    again = team["lead"].upload_report(team["run"]["run_id"])
    assert again["name"] != up["name"]


def test_members_see_only_their_pic(team):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    a = team["a"]
    assert a.list_reports()["reports"] == [{"name": name}]
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


def test_server_refuses_other_pic_file_even_to_a_modified_app(team):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    sb = team["a"]._sb()
    with pytest.raises(Exception, match="400|Object not found"):
        sb.download(f"{name}/{pic_file('PIC B')}")
    with pytest.raises(Exception):
        sb.download(f"{name}/lead.pmkt")


def test_lead_can_open_its_upload_fully(team):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    assert {d["pic"] for d in team["lead"].open_report(name)["result"]["digest"]} >= {"PIC A", "PIC B"}


def test_locked_member_loses_access_immediately(team):
    lead = team["lead"]
    old = lead.upload_report(team["run"]["run_id"])["name"]
    assert "error" not in lead.update_member("a@team.test", {"active": False})
    assert "error" in team["a"].open_report(old)
    assert "khoá" in sign_in(device(team["tmp"], "a5", team["sb"]), "a@team.test", team["pw_a"])["error"]
    assert "error" not in lead.update_member("a@team.test", {"active": True})
    assert "error" not in team["a"].open_report(old)
    assert "error" not in lead.remove_member("b@team.test")
    assert "error" in team["b"].open_report(old)


def test_member_on_new_device_reads_reports_uploaded_after_sign_in(team):
    a2 = device(team["tmp"], "a2", team["sb"])
    sign_in(a2, "a@team.test", team["pw_a"])
    assert len(team["sb"].members["a@team.test"]["enc_keys"]) == 2
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    assert "error" not in a2.open_report(name) and "error" not in team["a"].open_report(name)


@pytest.mark.parametrize("call", [
    lambda m: m.run([]), lambda m: m.export("PIC A", "/tmp/x.xlsx"), lambda m: m.save_style({}),
    lambda m: m.save_settings({"claude_note": "x"}), lambda m: m.apply_proposals(), lambda m: m.rewrite_message("PIC A"),
    lambda m: m.set_active_logic(1), lambda m: m.team_review(), lambda m: m.submit_feedback({"unit_id": "pl:PL Alpha"}),
    lambda m: m.upload_report(None), lambda m: m.add_member("x@team.test", "x", "PIC A"),
    lambda m: m.reset_password("b@team.test"), lambda m: m.remove_member("b@team.test"),
    lambda m: m.update_member("a@team.test", {"pic": "PIC B"}), lambda m: m.delete_report("x"), lambda m: m.members(),
])
def test_member_cannot_do_lead_actions(team, call):
    assert "Lead" in call(team["a"])["error"]


def test_member_settings_allowed_keys(team):
    assert "error" not in team["a"].save_settings({"language": "en", "ui_lang": "en"})


def test_lead_key_moves_to_new_device(team):
    key_file = team["tmp"] / "lead.pmktkey"
    assert "error" not in team["lead"].export_lead_key(str(key_file), "chuyen quyen 123")
    new = device(team["tmp"], "new", team["sb"])
    assert sign_in(new, LEAD, LEAD_PASSWORD)["needs_key"] is True
    assert "error" in new.upload_report(None)
    assert "error" in new.import_lead_key(str(key_file), "sai mat khau")
    assert new.import_lead_key(str(key_file), "chuyen quyen 123")["needs_key"] is False
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    assert "error" not in new.open_report(name)


def test_lead_key_reset(team):
    old = team["lead"].upload_report(team["run"]["run_id"])["name"]
    new = device(team["tmp"], "new", team["sb"])
    sign_in(new, LEAD, LEAD_PASSWORD)
    assert new.team_reset_lead_key()["needs_key"] is False
    assert "error" in team["a"].open_report(old)  # signed with the replaced key
    assert "khoá Lead" in team["lead"].upload_report(team["run"]["run_id"])["error"]  # stale key never publishes


def test_sign_out_forgets_session_and_sign_in_again_keeps_server(team):
    a = team["a"]
    assert a.team_sign_out()["signed_in"] is False
    assert "error" in a.list_reports()
    assert "error" not in a.team_connect(URL, "")  # keeps the saved key
    assert a.team_sign_in("a@team.test", team["pw_a"])["signed_in"]


def test_startup_file_open(team, tmp_path):
    name = team["lead"].upload_report(team["run"]["run_id"])["name"]
    f = tmp_path / "x.pmkt"
    f.write_bytes(team["sb"].objects[f"{name}/{pic_file('PIC A')}"])
    a = team["a"]
    a._startup_file = str(f)
    assert a.startup_open()["opened"]["file"] == "x.pmkt" and a.startup_open() == {"opened": None}


def test_register_file_type_commands():
    from pmkt_alert.app import file_type_entries
    e = file_type_entries(r"C:\Apps\PMKT-Alert.exe")
    assert (r"Software\Classes\.pmkt", "", "PMKTAlert.Run") in e
    assert (r"Software\Classes\PMKTAlert.Run\shell\open\command", "", '"C:\\Apps\\PMKT-Alert.exe" "%1"') in e


def test_bundled_server_needs_no_url_entry(tmp_path, monkeypatch):
    import pmkt_alert.api as api_mod
    monkeypatch.setattr(api_mod, "_bundled_team", lambda: {"url": URL, "anon": ANON})
    sb = FakeSupabase(LEAD)
    api = device(tmp_path, "x", sb)
    assert api.team_info()["bundled"] is True and api.team_info()["url"] == URL
    assert api.team_sign_in(LEAD, LEAD_PASSWORD)["role"] == "lead"  # no connect step: the server is built in

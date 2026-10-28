import json

import pytest

from pmkt_alert.api import Api
from pmkt_alert.claude import ClaudeError, ClaudeStatus
from pmkt_alert.store import Store

OK = lambda: ClaudeStatus(True, "2.1", True, True, 1.0, None)  # noqa: E731
PASS = "mật khẩu nhóm dài 2026!"


def no_claude(*a, **k):
    raise ClaudeError("x")


@pytest.fixture()
def team(tmp_path, synthetic_paths):
    share = tmp_path / "share"
    share.mkdir()
    lead = Api(Store(tmp_path / "lead"), status_fn=OK, ask_fn=no_claude)
    code = lead.setup_lead(PASS, str(share))["invite_code"]
    run = lead.run([str(p) for p in synthetic_paths])
    return lead, code, share, run


def test_lead_setup_and_publish(team):
    lead, code, share, run = team
    assert code.startswith("PMKT-") and lead.role_info()["role"] == "lead"
    files = list(share.glob("*.pmkt"))
    assert len(files) == 1 and run["published"] == files[0].name
    assert b"PIC A" not in files[0].read_bytes()  # encrypted


def test_short_passphrase_rejected(tmp_path):
    assert "error" in Api(Store(tmp_path), status_fn=OK).setup_lead("ngắn", str(tmp_path))


def test_member_sees_lead_results(team, tmp_path):
    lead, code, share, run = team
    m = Api(Store(tmp_path / "m"), status_fn=OK, ask_fn=no_claude)
    out = m.setup_member(code, PASS, "PIC A", str(share))
    assert out["role"] == "member" and out["opened"]
    res = m.results()
    assert res["result"]["digest"] == run["result"]["digest"] and res["published_by"]
    ev = m.evidence("pl:PL Alpha")
    assert "error" not in ev and ev["sections"][0]["rows"]
    assert "error" not in m.dashboard()
    json.dumps(res, allow_nan=False)


@pytest.mark.parametrize("call", [
    lambda m: m.run([]), lambda m: m.export("PIC A", "/tmp/x.xlsx"), lambda m: m.save_style({}),
    lambda m: m.save_settings({"claude_note": "x"}), lambda m: m.apply_proposals(), lambda m: m.rewrite_message("PIC A"),
    lambda m: m.set_active_logic(1), lambda m: m.team_review(), lambda m: m.submit_feedback({"unit_id": "pl:PL Alpha"}),
])
def test_member_cannot_do_lead_actions(team, tmp_path, call):
    lead, code, share, run = team
    m = Api(Store(tmp_path / "m"), status_fn=OK, ask_fn=no_claude)
    m.setup_member(code, PASS, "PIC A", str(share))
    assert "Lead" in call(m)["error"]


def test_member_wrong_passphrase_or_code(team, tmp_path):
    lead, code, share, run = team
    m = Api(Store(tmp_path / "m"), status_fn=OK)
    assert "mật khẩu" in m.setup_member(code, "sai mật khẩu nhé!!", "PIC A", str(share))["error"]
    other = Api(Store(tmp_path / "x"), status_fn=OK).setup_lead(PASS, str(tmp_path / "x"))["invite_code"]
    assert "chữ ký" in Api(Store(tmp_path / "m2"), status_fn=OK).setup_member(other, PASS, "PIC A", str(share))["error"].lower()


def test_member_settings_allowed_keys(team, tmp_path):
    lead, code, share, run = team
    m = Api(Store(tmp_path / "m"), status_fn=OK)
    m.setup_member(code, PASS, "PIC A", str(share))
    assert "error" not in m.save_settings({"language": "en", "my_pic": "PIC B"})


def test_change_passphrase_and_transfer_lead(team, tmp_path):
    lead, code, share, run = team
    assert "error" not in lead.change_passphrase("mật khẩu mới dài 2027!")
    key_file = tmp_path / "lead.pmktkey"
    assert "error" not in lead.export_lead_key(str(key_file), "chuyen quyen 123")
    new = Api(Store(tmp_path / "new"), status_fn=OK)
    out = new.import_lead_key(str(key_file), "chuyen quyen 123", "mật khẩu mới dài 2027!", str(share))
    assert out["invite_code"] == code  # members keep the same code
    assert "error" in Api(Store(tmp_path / "bad"), status_fn=OK).import_lead_key(str(key_file), "sai", PASS, str(share))

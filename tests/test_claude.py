import json
import subprocess

import pytest

from pmkt_alert.claude import ClaudeError, ask, check_status, filter_grounded, grounded, numbers_in
from pmkt_alert.prompts import STYLE_SCHEMA
import pmkt_alert.claude as claude_mod


@pytest.fixture(autouse=True)
def claude_on_path(monkeypatch):
    monkeypatch.setattr(claude_mod.shutil, "which", lambda name: r"C:\npm\claude.cmd")


def ok(out, code=0, err=""):
    return lambda *a, **k: subprocess.CompletedProcess(a[0], code, out, err)


def raise_(exc):
    def f(*a, **k):
        raise exc
    return f


def fake(table):
    def run(args, **kw):
        for key, fn in table.items():
            if key in args:
                return fn(args, **kw)
        raise AssertionError(args)
    return run


def test_status_not_installed():
    s = check_status(runner=raise_(FileNotFoundError()))
    assert not s.installed and s.level == "bad"


def test_status_logged_out():
    s = check_status(runner=fake({"--version": ok("2.1.0 (Claude Code)"),
                                  "-p": ok(json.dumps({"is_error": True, "result": "Invalid API key · Please run /login"}))}))
    assert s.installed and s.version == "2.1.0 (Claude Code)" and not s.logged_in and s.level == "bad"


def test_status_ok_and_slow():
    s = check_status(runner=fake({"--version": ok("2.1.0"), "-p": ok(json.dumps({"is_error": False, "result": "OK"}))}))
    assert s.level == "ok" and s.latency_s is not None
    t = check_status(runner=fake({"--version": ok("2.1.0"), "-p": raise_(subprocess.TimeoutExpired("claude", 45))}))
    assert t.installed and t.logged_in and not t.responds and t.level == "warn"


def test_ask_uses_isolated_flags():
    seen = {}

    def run(args, **kw):
        seen["args"], seen["input"] = args, kw.get("input")
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": '{"slack": "hi"}'}), "")
    assert ask("prompt-text", STYLE_SCHEMA, runner=run) == {"slack": "hi"}
    assert seen["input"] == "prompt-text"
    assert {"--tools", "--strict-mcp-config", "--no-session-persistence"} <= set(seen["args"])


def test_ask_tolerates_fences_and_validates():
    out = ask("x", STYLE_SCHEMA, runner=fake({"-p": ok(json.dumps({"result": "Đây:\n```json\n{\"slack\": \"hi\"}\n```"}))}))
    assert out == {"slack": "hi"}
    with pytest.raises(ClaudeError):
        ask("x", STYLE_SCHEMA, runner=fake({"-p": ok(json.dumps({"result": "Sorry, I can't"}))}))
    with pytest.raises(ClaudeError):
        ask("x", STYLE_SCHEMA, runner=fake({"-p": ok(json.dumps({"result": '{"other": 1}'}))}))
    with pytest.raises(ClaudeError):
        ask("x", STYLE_SCHEMA, runner=raise_(subprocess.TimeoutExpired("claude", 1)))
    with pytest.raises(ClaudeError):
        ask("x", STYLE_SCHEMA, runner=fake({"-p": ok("not json at all", code=1)}))


def test_numbers_in_ignores_dates_and_small_counts():
    assert numbers_in("ngày 19/10, T10, spend x2 và 3 camp") == []
    assert numbers_in("$2,602.93 · 91% · 2.6k") == [(2602.93, False, 2), (91.0, True, 0), (2600.0, False, -2)]  # k: precision 10^2


def test_grounded():
    rows = [{"spend_mtd": 2602.93, "pct_spend": 0.912384, "excess": 51.7737, "d_spend": -0.5452}]
    assert grounded("đã tiêu $2,602.93, 91% budget, dư chi $51.77 ngày 19/10, spend −55%", rows)
    assert grounded("đốt 2.6k rồi", rows)
    assert not grounded("đã tiêu $3,000", rows)
    assert grounded("không có số", rows)


def test_filter_grounded():
    rows = {"pl:A": {"unit_id": "pl:A", "spend_mtd": 100.0}}
    items = [{"text": "tiêu $100", "refs": ["pl:A"]}, {"text": "tiêu $500", "refs": ["pl:A"]},
             {"text": "tiêu $100", "refs": ["pl:missing"]}, {"text": "7 PL HIGH", "refs": []}]
    kept, dropped = filter_grounded(items, rows, ("text",), implicit=[{"pl_high": 7}])
    assert [k["text"] for k in kept] == ["tiêu $100", "7 PL HIGH"] and len(dropped) == 2


def test_resolves_claude_cmd_via_which():
    seen = []
    run = lambda args, **kw: seen.append(args) or subprocess.CompletedProcess(args, 0, json.dumps({"result": '{"slack": "x"}'}), "")
    ask("p", STYLE_SCHEMA, runner=run)
    assert seen[0][0] == r"C:\npm\claude.cmd"


def test_not_on_path_is_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(claude_mod.Path, "home", lambda: tmp_path)
    s = check_status(runner=raise_(AssertionError("must not run")))
    assert not s.installed and s.level == "bad"


def test_decode_errors_replaced():
    seen = {}
    def run(args, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": '{"slack": "x"}'}), "")
    ask("p", STYLE_SCHEMA, runner=run)
    assert seen["errors"] == "replace"


def test_retryable_flags():
    with pytest.raises(ClaudeError) as e1:
        ask("x", STYLE_SCHEMA, runner=fake({"-p": ok(json.dumps({"result": "prose"}))}))
    assert e1.value.retryable is True
    with pytest.raises(ClaudeError) as e2:
        ask("x", STYLE_SCHEMA, runner=raise_(subprocess.TimeoutExpired("claude", 1)))
    assert e2.value.retryable is False


def test_finds_claude_in_install_dir_when_not_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(claude_mod.Path, "home", lambda: tmp_path)
    assert claude_mod._exe() is None
    exe = tmp_path / ".local" / "bin" / ("claude.exe" if claude_mod.sys.platform == "win32" else "claude")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert claude_mod._exe() == str(exe)


def test_install_commands_are_official(monkeypatch):
    monkeypatch.setattr(claude_mod.sys, "platform", "win32")
    assert claude_mod.install_command()[-1] == "irm https://claude.ai/install.ps1 | iex"
    monkeypatch.setattr(claude_mod.sys, "platform", "darwin")
    assert claude_mod.install_command() == ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]


def test_install_success_and_failure(monkeypatch):
    found = {"v": None}
    monkeypatch.setattr(claude_mod, "_exe", lambda: found["v"])

    def ok_run(args, **kw):
        found["v"] = "/home/u/.local/bin/claude"
        return subprocess.CompletedProcess(args, 0, "Claude Code successfully installed!", "")
    out = claude_mod.install(runner=ok_run)
    assert out["ok"] is True and "successfully" in out["output"]

    found["v"] = None
    out = claude_mod.install(runner=lambda a, **k: subprocess.CompletedProcess(a, 1, "", "curl: (6) Could not resolve host"))
    assert out["ok"] is False and "Could not resolve host" in out["output"]
    out = claude_mod.install(runner=raise_(subprocess.TimeoutExpired("x", 600)))
    assert out["ok"] is False


def test_login_command_opens_terminal(monkeypatch):
    monkeypatch.setattr(claude_mod.sys, "platform", "darwin")
    cmd = claude_mod.login_command("/u/.local/bin/claude")
    assert cmd[0] == "osascript" and "/u/.local/bin/claude" in " ".join(cmd)
    monkeypatch.setattr(claude_mod.sys, "platform", "win32")
    cmd = claude_mod.login_command(r"C:\u\.local\bin\claude.exe")
    assert cmd[:3] == ["cmd", "/c", "start"] and cmd[-1] == r"C:\u\.local\bin\claude.exe" and "/k" in cmd


def test_numbers_after_a_word_are_checked():
    rows = [{"pct_spend": 2.16, "excess": 38.43}]
    assert grounded("Spend 216% và dư chi 38.43", rows)
    assert not grounded("Spend 999%", rows)
    assert not grounded("tiêu 2602 rồi", rows)
    assert grounded("spend x2, L7D, T10", rows)  # glued to a word: not a quoted figure


def test_grounded_accepts_numeric_string_fields():
    rows = [{"campaign_id": "212121537347072", "excess": 38.43}]
    assert grounded("camp 212121537347072 dư chi $38.43", rows)
    assert not grounded("camp 999999999999999", rows)


def test_vietnamese_number_formats_and_dash_dates():
    rows = [{"gmv_mtd": 187268.4, "target": 233601.2, "tacos": 0.107, "excess": 527.64, "high": 19}]
    assert grounded("GMV MTD 187.268 / target 233.601, TACoS 10,7%, excess 527,64 (tuần 2026-10-19, 10-05)", rows)
    assert grounded("excess 527.64 và GMV 187,268", rows)
    assert not grounded("GMV MTD 999.999", rows)
    assert not grounded("TACoS 12,5%", rows)


def test_numbers_inside_names_and_units_are_ignored():
    rows = [{"campaign": "Camp SB PT 18lbs & 35lbs", "pl": "Roller Foam - Single 20 lbs", "excess": 61.27}]
    assert grounded("2 camp SB PT 18lbs & 35lbs: excess $61.27", rows)
    assert grounded("PL Roller Foam - Single 20 lbs đang overspend", rows)
    assert not grounded("excess $61.99", rows)

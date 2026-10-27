import json
import subprocess

import pytest

from pmkt_alert.claude import ClaudeError, ask, check_status, filter_grounded, grounded, numbers_in
from pmkt_alert.prompts import STYLE_SCHEMA


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

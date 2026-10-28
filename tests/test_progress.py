from pmkt_alert.progress import Eta


def test_eta_uses_history_and_parallel_claude_calls():
    eta = Eta({"load": 4.0, "rules": 6.0, "logic_eval": 10.0, "claude_call": 20.0}, parallel=4)
    eta.plan(["load", "rules", "claude", "logic_eval"], claude_calls=8)
    assert eta.remaining() == 4 + 6 + 8 * 20 / 4 + 10
    eta.start("load", now=0); eta.done("load", now=3)
    assert eta.remaining() == 6 + 40 + 10
    eta.calls_done(4)
    assert eta.remaining() == 6 + 20 + 10
    assert eta.learned()["load"] == 0.5 * 4 + 0.5 * 3  # smoothed, not replaced


def test_eta_defaults_and_running_step_counts_down():
    eta = Eta({}, parallel=4)
    eta.plan(["rules"], claude_calls=0)
    eta.start("rules", now=100)
    full = eta.remaining(now=100)
    assert 0 < full and eta.remaining(now=102) == max(0, full - 2)


def test_learns_claude_call_time():
    eta = Eta({}, parallel=4)
    eta.plan(["claude"], claude_calls=4)
    eta.start("claude", now=0); eta.calls_done(4); eta.done("claude", now=40)
    assert eta.learned()["claude_call"] != Eta.DEFAULTS["claude_call"]

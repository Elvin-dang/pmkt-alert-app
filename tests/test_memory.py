import os
import time

from pmkt_alert.store import Store


def _run(s, as_of, pad=0):
    return s.save_run({"as_of": as_of, "logic_version": 1, "pl": [], "camp": [], "digest": [], "pad": "x" * pad}, None)


def test_usage_reports_size_breakdown_and_oldest(tmp_path):
    s = Store(tmp_path)
    r1 = _run(s, "2026-10-01", 5000)
    os.utime(s.base / "runs" / f"{r1}.json", (time.time() - 86400 * 10,) * 2)
    _run(s, "2026-10-19", 5000)
    s.add_lesson("bài học", "x")
    u = s.usage()
    assert u["limit_bytes"] == 1024 ** 3 and u["bytes"] >= 10000
    assert u["by_kind"]["runs"] >= 10000 and u["by_kind"]["lessons"] > 0
    assert u["runs"] == 2 and u["oldest"]["run_id"] == r1 and u["oldest"]["date"]


def test_prune_removes_oldest_runs_only(tmp_path):
    s = Store(tmp_path)
    ids = []
    for i in range(4):
        ids.append(_run(s, f"2026-10-0{i + 1}", 20000))
        os.utime(s.base / "runs" / f"{ids[-1]}.json", (time.time() - 1000 * (10 - i),) * 2)
    s.add_lesson("giữ lại", "x")
    deleted = s.prune(limit_bytes=45000)
    left = [r["run_id"] for r in s.list_runs()]
    assert deleted == [ids[0], ids[1]] and ids[3] in left and s.lessons()[0]["text"] == "giữ lại"


def test_prune_never_deletes_latest_run(tmp_path):
    s = Store(tmp_path)
    only = _run(s, "2026-10-19", 50000)
    assert s.prune(limit_bytes=10) == [] and [r["run_id"] for r in s.list_runs()] == [only]


def test_auto_prune_on_save_when_enabled(tmp_path):
    s = Store(tmp_path)
    s.save_settings({"memory_limit_mb": 0.03, "auto_prune": True})  # ~31 KB
    first = _run(s, "2026-10-01", 20000)
    os.utime(s.base / "runs" / f"{first}.json", (time.time() - 100,) * 2)
    _run(s, "2026-10-02", 20000)
    assert first not in [r["run_id"] for r in s.list_runs()]
    s.save_settings({"auto_prune": False})
    a = _run(s, "2026-10-03", 20000)
    assert len(s.list_runs()) == 2 and a in [r["run_id"] for r in s.list_runs()]


def test_limit_capped_at_1gb(tmp_path):
    s = Store(tmp_path)
    s.save_settings({"memory_limit_mb": 5000})
    assert s.usage()["limit_bytes"] == 1024 ** 3

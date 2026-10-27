import hashlib
import io
import json
import urllib.error
from pathlib import Path

import pytest

from pmkt_alert.updater import Release, download_verified, is_newer, latest_release, parse_version, recent_releases

REL = {"tag_name": "v1.3.0", "body": "## Mới\n- a", "published_at": "2026-10-26T00:00:00Z",
       "assets": [{"name": "PMKT-Alert-v1.3.0.exe", "browser_download_url": "u1"},
                  {"name": "PMKT-Alert-v1.3.0.exe.sha256", "browser_download_url": "u2"}]}


def fake_json(obj):
    return lambda req, timeout=None: io.BytesIO(json.dumps(obj).encode())


def fake_bytes(table):
    return lambda req, timeout=None: io.BytesIO(table[getattr(req, "full_url", req)])


def raise_(exc):
    def f(*a, **k):
        raise exc
    return f


def test_versions():
    assert parse_version("v1.2.3") == (1, 2, 3) and parse_version("0.0.0-dev") == (0, 0, 0)
    assert is_newer("v1.3.0", "1.2.1") and not is_newer("v1.2.1", "1.2.1") and is_newer("v0.1.0", "0.0.0-dev")
    assert not is_newer("garbage", "1.0.0")


def test_latest_release_parses_assets():
    rel = latest_release("o/r", fetch=fake_json(REL))
    assert rel.tag == "v1.3.0" and rel.exe_url == "u1" and rel.sha_url == "u2" and rel.notes.startswith("## Mới")


def test_release_without_exe_is_none():
    assert latest_release("o/r", fetch=fake_json({**REL, "assets": []})) is None


def test_offline_or_404_returns_none():
    assert latest_release("o/r", fetch=raise_(urllib.error.URLError("offline"))) is None
    assert latest_release("o/r", fetch=raise_(urllib.error.HTTPError("u", 404, "nf", {}, None))) is None
    assert latest_release("", fetch=fake_json(REL)) is None


def test_recent_releases():
    rels = recent_releases("o/r", fetch=fake_json([REL, {**REL, "tag_name": "v1.2.0"}]))
    assert [r.tag for r in rels] == ["v1.3.0", "v1.2.0"]


def test_download_verified_ok(tmp_path):
    body = b"exe-bytes"
    sha = hashlib.sha256(body).hexdigest().upper().encode() + b"  PMKT-Alert-v1.exe"
    rel = Release("v1", "", "", "https://x/PMKT-Alert-v1.exe", "https://x/PMKT-Alert-v1.exe.sha256")
    out = download_verified(rel, tmp_path, fetch=fake_bytes({rel.exe_url: body, rel.sha_url: sha}))
    assert out.name == "PMKT-Alert-v1.exe" and out.read_bytes() == body and not list(tmp_path.glob("*.part"))


def test_checksum_mismatch_deletes(tmp_path):
    rel = Release("v1", "", "", "https://x/a.exe", "https://x/a.exe.sha256")
    with pytest.raises(ValueError, match="Checksum"):
        download_verified(rel, tmp_path, fetch=fake_bytes({rel.exe_url: b"abc", rel.sha_url: b"deadbeef  a.exe"}))
    assert not list(tmp_path.iterdir())

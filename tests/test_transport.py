import io
import json
import urllib.error

import pytest

from pmkt_alert.transport import FolderTransport, SupabaseTransport, TransportError


def test_folder_roundtrip(tmp_path):
    t = FolderTransport(str(tmp_path))
    t.upload("a.pmkt", b"1")
    t.upload("b.pmkt", b"22")
    assert [r["name"] for r in t.list()] == ["b.pmkt", "a.pmkt"] and t.download("a.pmkt") == b"1"
    with pytest.raises(TransportError):
        t.upload("a.pmkt", b"again")  # never overwrite a published report
    t.delete("a.pmkt")
    assert [r["name"] for r in t.list()] == ["b.pmkt"]


class Fake:
    def __init__(self, responses):
        self.responses, self.requests = responses, []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(r if isinstance(r, bytes) else json.dumps(r).encode())


def test_supabase_calls():
    f = Fake([[{"name": "PMKT-Alert_2026-10-28_15-42.pmkt", "created_at": "2026-10-28T08:42:00Z", "metadata": {"size": 123}},
               {"name": ".emptyFolderPlaceholder", "metadata": {}}],
              {"Key": "reports/x.pmkt"}, b"BLOB",
              {"access_token": "AT", "refresh_token": "RT"}])
    t = SupabaseTransport("https://p.supabase.co/", "ANON", opener=f)
    assert t.list() == [{"name": "PMKT-Alert_2026-10-28_15-42.pmkt", "size": 123, "updated": "2026-10-28T08:42:00Z"}]
    lst = f.requests[0]
    assert lst.full_url == "https://p.supabase.co/storage/v1/object/list/reports" and lst.get_header("Apikey") == "ANON"
    t.token = "LEADTOKEN"
    t.upload("x.pmkt", b"abc")
    up = f.requests[1]
    assert up.full_url == "https://p.supabase.co/storage/v1/object/reports/x.pmkt" and up.get_header("Authorization") == "Bearer LEADTOKEN"
    assert up.get_header("X-upsert") == "false" and up.data == b"abc"
    assert t.download("x.pmkt") == b"BLOB"
    assert t.login("lead@example.com", "pw") == ("AT", "RT")
    assert "grant_type=password" in f.requests[3].full_url


def test_supabase_errors_are_readable():
    err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b'{"message":"new row violates row-level security policy"}'))
    t = SupabaseTransport("https://p.supabase.co", "ANON", opener=Fake([err]))
    with pytest.raises(TransportError, match="quyền"):
        t.upload("x.pmkt", b"1")
    t2 = SupabaseTransport("https://p.supabase.co", "ANON", opener=Fake([urllib.error.URLError("offline")]))
    with pytest.raises(TransportError, match="kết nối"):
        t2.list()

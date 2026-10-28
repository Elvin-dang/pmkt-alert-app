import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("provision", Path(__file__).parents[1] / "scripts" / "provision_supabase.py")
prov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prov)


class FakeApi:
    def __init__(self):
        self.calls = []
        self.health = ["COMING_UP", "ACTIVE_HEALTHY"]

    def __call__(self, method, url, token, body=None, apikey=None):
        self.calls.append((method, url.replace("https://api.supabase.com/v1", ""), token, body))
        path = url.replace("https://api.supabase.com/v1", "")
        if path == "/organizations":
            return 200, [{"id": "org1", "name": "Mine"}]
        if path == "/projects" and method == "POST":
            return 201, {"id": "refx"}
        if path == "/projects/refx":
            return 200, {"status": self.health.pop(0)}
        if path.endswith("/api-keys?reveal=true"):
            return 200, [{"name": "anon", "api_key": "ANON"}, {"name": "service_role", "api_key": "SERVICE"}]
        if url.endswith("/auth/v1/admin/users"):
            assert token == "SERVICE" and apikey == "SERVICE"
            return 200, {"id": "uid-1"}
        return 200, None


def test_provision_new_project(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", "sbp_test")
    api, deployed = FakeApi(), []
    out = tmp_path / "team.json"
    r = prov.provision("Lead@Co.test", None, None, http=api, deploy=lambda ref, tok: deployed.append(ref),
                       sleep=lambda s: None, home=tmp_path, out=out)
    assert r == {"ref": "refx", "url": "https://refx.supabase.co"} and deployed == ["refx"]
    assert json.loads(out.read_text()) == {"url": "https://refx.supabase.co", "anon": "ANON"}  # never the service key
    steps = [(m, p.split("?")[0]) for m, p, _, _ in api.calls]
    assert ("POST", "/projects/refx/database/query") in steps and ("PATCH", "/projects/refx/config/auth") in steps
    sql = next(b["query"] for m, p, _, b in api.calls if p.endswith("/database/query"))
    assert "'lead@co.test', 'lead'" in sql
    auth = next(b for m, p, _, b in api.calls if p.endswith("/config/auth"))
    assert auth["disable_signup"] is True
    login = (tmp_path / "PMKT-Lead-login.txt").read_text()
    assert "lead@co.test" in login and oct((tmp_path / "PMKT-Lead-login.txt").stat().st_mode)[-3:] == "600"
    link = next(b for m, p, _, b in api.calls if "pmkt_members?email=eq.lead@co.test" in p)
    assert link == {"user_id": "uid-1"}

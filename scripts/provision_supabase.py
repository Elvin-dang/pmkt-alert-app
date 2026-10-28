"""One-time (re-runnable) setup of the team's Supabase project – run by the app owner, never by a Lead.

    python scripts/provision_supabase.py --lead-email lead@company.com [--project-ref abcd...] [--org ORG_ID]

Reads a Supabase personal access token from $SUPABASE_ACCESS_TOKEN or ~/.supabase-pmkt-token (create one at
supabase.com → Account → Access Tokens). It never prints or stores the token or the service key.
1. creates the project (or uses --project-ref) and waits until it is healthy
2. runs the schema + row-level security SQL (pmkt_alert.supabase.setup_sql)
3. disables public sign-ups (accounts are created by Leads in the app)
4. deploys the pmkt-admin function (account management, holds the service key server-side)
5. creates the first Lead's login; the password goes to ~/PMKT-Lead-login.txt (readable only by you)
6. writes src/pmkt_alert/team.json (project URL + public anon key) – commit it; every build then has the server built in
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pmkt_alert.supabase import setup_sql  # noqa: E402

API = "https://api.supabase.com/v1"


class Http:
    def __init__(self, opener=urllib.request.urlopen):
        self.opener = opener

    def __call__(self, method: str, url: str, token: str, body=None, apikey: str | None = None):
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if apikey:
            headers["apikey"] = apikey
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers,
                                     method=method)
        try:
            with self.opener(req, timeout=120) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")


def access_token() -> str:
    tok = os.environ.get("SUPABASE_ACCESS_TOKEN") or ""
    f = Path.home() / ".supabase-pmkt-token"
    if not tok and f.exists():
        tok = f.read_text().strip()
    if not tok:
        sys.exit("Need a Supabase access token in $SUPABASE_ACCESS_TOKEN or ~/.supabase-pmkt-token")
    return tok


def ok(status_body, what):
    status, body = status_body
    if status >= 300:
        sys.exit(f"{what} failed ({status}): {body}")
    return body


def provision(lead_email: str, ref: str | None, org: str | None, http=None, deploy=None, sleep=time.sleep,
              home: Path = Path.home(), out: Path = ROOT / "src" / "pmkt_alert" / "team.json") -> dict:
    http, tok = http or Http(), access_token()
    if not ref:
        orgs = ok(http("GET", f"{API}/organizations", tok), "List organizations")
        if not org:
            if len(orgs) != 1:
                sys.exit("Several organizations – pass --org: " + ", ".join(f"{o['id']} ({o['name']})" for o in orgs))
            org = orgs[0]["id"]
        proj = ok(http("POST", f"{API}/projects", tok, {"name": "pmkt-alert", "organization_id": org,
                                                       "region": "ap-southeast-1", "db_pass": secrets.token_urlsafe(24)}),
                  "Create project")
        ref = proj["id"]
        print(f"Created project {ref}")
    for _ in range(90):
        status = ok(http("GET", f"{API}/projects/{ref}", tok), "Read project")["status"]
        if status == "ACTIVE_HEALTHY":
            break
        sleep(10)
    else:
        sys.exit(f"Project {ref} is not healthy yet ({status}); run again in a few minutes with --project-ref {ref}")
    url = f"https://{ref}.supabase.co"

    ok(http("POST", f"{API}/projects/{ref}/database/query", tok, {"query": setup_sql(lead_email)}), "Schema SQL")
    ok(http("PATCH", f"{API}/projects/{ref}/config/auth", tok, {"disable_signup": True, "password_min_length": 10}),
       "Auth settings")

    keys = ok(http("GET", f"{API}/projects/{ref}/api-keys?reveal=true", tok), "API keys")
    by_name = {k.get("name"): k.get("api_key") for k in keys}
    anon = by_name.get("anon") or next((k["api_key"] for k in keys if k.get("type") == "publishable"), None)
    service = by_name.get("service_role") or next((k["api_key"] for k in keys if k.get("type") == "secret"), None)
    if not anon or not service:
        sys.exit("Could not read the project's API keys")

    (deploy or deploy_function)(ref, tok)

    lead = lead_email.strip().lower()
    password = "-".join(secrets.token_urlsafe(6)[:5] for _ in range(3))
    status, body = http("POST", f"{url}/auth/v1/admin/users", service,
                        {"email": lead, "password": password, "email_confirm": True}, apikey=service)
    if status < 300:
        ok(http("PATCH", f"{url}/rest/v1/pmkt_members?email=eq.{lead}", service, {"user_id": body["id"]}, apikey=service),
           "Link Lead login")
        f = home / "PMKT-Lead-login.txt"
        f.write_text(f"PMKT Alert – first Lead login\nemail: {lead}\npassword: {password}\n"
                     "Change it in the app: Settings → Team → New password.\n", encoding="utf-8")
        f.chmod(0o600)
        print(f"Lead login created – password saved to {f}")
    elif "already" in json.dumps(body):
        print("Lead login already exists – kept its password")
    else:
        sys.exit(f"Create Lead login failed ({status}): {body}")

    out.write_text(json.dumps({"url": url, "anon": anon}, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} – commit it.")
    return {"ref": ref, "url": url}


def deploy_function(ref: str, tok: str) -> None:
    r = subprocess.run(["npx", "--yes", "supabase", "functions", "deploy", "pmkt-admin", "--project-ref", ref, "--use-api"],
                       cwd=ROOT, env={**os.environ, "SUPABASE_ACCESS_TOKEN": tok}, capture_output=True, text=True)
    if r.returncode:
        sys.exit("Deploy pmkt-admin failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    print("Deployed function pmkt-admin")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lead-email", required=True)
    ap.add_argument("--project-ref")
    ap.add_argument("--org")
    a = ap.parse_args()
    provision(a.lead_email, a.project_ref, a.org)

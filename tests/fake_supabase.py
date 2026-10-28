"""In-memory stand-in for the Supabase endpoints PMKT Alert calls, with the same rules as supabase.setup_sql
(those rules are tested against real Postgres in test_team_sql.py). Plug in as Supabase(opener=fake)."""
import hashlib
import io
import json
import secrets
import urllib.error
import urllib.parse


LEAD_PASSWORD = "lead-password-1"


class FakeSupabase:
    """Mirrors supabase.setup_sql (RLS) and supabase/functions/pmkt-admin (account management)."""

    def __init__(self, lead_email: str):
        self.members = {lead_email: {"email": lead_email, "role": "lead", "pic": None, "name": "Lead", "enc_keys": [],
                                     "sign_pub": None, "active": True}}
        self.passwords: dict[str, str] = {lead_email: LEAD_PASSWORD}  # auth.users: email → password
        self.banned: set[str] = set()
        self.tokens: dict[str, str] = {}  # access or refresh token → email
        self.objects: dict[str, bytes] = {}
        self.sent: list[str] = []

    # -- helpers mirroring the SQL functions
    def _row(self, email):
        r = self.members.get(email)
        return r if r and r["active"] else None

    def is_lead(self, email):
        r = self._row(email)
        return bool(r and r["role"] == "lead")

    def my_file(self, email):
        r = self._row(email)
        return hashlib.md5(r["pic"].encode()).hexdigest() + ".pmkt" if r and r["role"] == "member" and r["pic"] else None

    def can_read(self, email, path):
        return self.is_lead(email) or (email and path.split("/")[-1] == self.my_file(email))

    # -- HTTP
    def __call__(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        body = json.loads(req.data) if req.data and req.get_header("Content-type") == "application/json" else req.data
        assert req.get_header("Apikey") == "ANON"
        auth = req.get_header("Authorization", "")
        assert auth.startswith("Bearer AT") or not auth  # only a user's session token, never the API key
        token = auth.removeprefix("Bearer ")
        who = self.tokens.get(token)
        status, out = self.route(req.get_method(), url.path, urllib.parse.parse_qs(url.query), body, who, req)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(json.dumps(out).encode()))
        return io.BytesIO(out if isinstance(out, bytes) else json.dumps(out).encode() if out is not None else b"")

    def _session(self, email):
        at, rt = "AT" + secrets.token_hex(4), "RT" + secrets.token_hex(4)
        self.tokens[at] = self.tokens[rt] = email
        return {"access_token": at, "refresh_token": rt}

    def route(self, method, path, q, body, who, req):
        if path == "/auth/v1/token" and q.get("grant_type") == ["password"]:
            email = body["email"]
            if self.passwords.get(email) != body["password"]:
                return 400, {"error_description": "Invalid login credentials"}
            if email in self.banned:
                return 400, {"msg": "User is banned"}
            return 200, self._session(email)
        if path == "/auth/v1/token":
            email = self.tokens.pop(body["refresh_token"], None)
            if email in self.banned or email not in self.passwords:
                return 400, {"error_description": "Invalid Refresh Token"}
            return (200, self._session(email)) if email else (400, {"error_description": "Invalid Refresh Token"})
        if path == "/auth/v1/logout":
            return 204, None
        if not who:
            return 401, {"message": "JWT required"}
        if path == "/auth/v1/user" and method == "PUT":
            self.passwords[who] = body["password"]
            return 200, {}
        if path == "/functions/v1/pmkt-admin":
            return self.admin(who, body)
        if path == "/rest/v1/pmkt_members":
            eq = q.get("email", [""])[0].removeprefix("eq.")
            visible = [r for r in self.members.values()
                       if r["email"] == who or (r["role"] == "lead" and r["active"]) or self.is_lead(who)]
            if method == "GET":
                return 200, [dict(r) for r in visible if not eq or r["email"] == eq]
            if not self.is_lead(who):
                return (200, []) if method in ("PATCH", "DELETE") else (403, {"message": "new row violates row-level security policy"})
            if method == "POST":
                if body["email"] != body["email"].lower() or body["email"] in self.members:
                    return 409, {"message": "duplicate key or bad email"}
                row = {"pic": None, "name": None, "enc_keys": [], "sign_pub": None, "active": True, **body}
                self.members[row["email"]] = row
                return 201, [row]
            if method == "PATCH":
                if eq not in self.members:
                    return 200, []
                self.members[eq].update(body)
                return 200, [self.members[eq]]
            if method == "DELETE":
                self.members.pop(eq, None)
                return 204, None
        if path == "/rest/v1/rpc/pmkt_register_keys":
            r = self._row(who)
            if r:
                keys = [k for k in r["enc_keys"] if k != body["p_enc"]] + [body["p_enc"]]
                r["enc_keys"] = keys[-3:]
                if r["role"] == "lead" and body["p_sign"] and (r["sign_pub"] is None or body.get("p_reset")):
                    r["sign_pub"] = body["p_sign"]
            return 204, None
        if path == "/storage/v1/object/list/reports":
            prefix = body["prefix"]
            names = [p for p in self.objects if p.startswith(prefix) and self.can_read(who, p)]
            if prefix:
                return 200, [{"id": "x", "name": p[len(prefix):]} for p in names]
            return 200, [{"id": None, "name": f} for f in sorted({p.split("/")[0] for p in names}, reverse=True)]
        if path.startswith("/storage/v1/object/reports/"):
            obj = urllib.parse.unquote(path.removeprefix("/storage/v1/object/reports/"))
            if method == "POST":
                if not self.is_lead(who):
                    return 403, {"message": "new row violates row-level security policy"}
                if obj in self.objects:
                    return 409, {"message": "The resource already exists"}
                self.objects[obj] = body
                return 200, {"Key": obj}
            if method == "GET":
                return (200, self.objects[obj]) if obj in self.objects and self.can_read(who, obj) else (400, {"message": "Object not found"})
        if path == "/storage/v1/object/reports" and method == "DELETE":
            if self.is_lead(who):
                for p in body["prefixes"]:
                    self.objects.pop(p, None)
            return 200, []
        return 404, {"message": f"fake: no route {method} {path}"}

    def admin(self, caller, body):
        """Same rules as supabase/functions/pmkt-admin/index.ts (tested with Deno)."""
        if not self.is_lead(caller):
            return 403, {"error": "Chỉ Lead được quản lý tài khoản"}
        email = str(body.get("email", "")).strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            return 400, {"error": "Email không hợp lệ"}
        if "password" in body and len(body["password"]) < 10:
            return 400, {"error": "Mật khẩu cần ít nhất 10 ký tự"}
        if email == caller and body["action"] in ("delete", "set_active"):
            return 400, {"error": "Không thể khoá hoặc xoá chính tài khoản đang dùng"}
        if body["action"] == "create":
            role = "lead" if body.get("role") == "lead" else "member"
            pic = (body.get("pic") or "").strip() if role == "member" else None
            if role == "member" and not pic:
                return 400, {"error": "Thành viên cần có PIC"}
            if email in self.members or email in self.passwords:
                return 409, {"error": "Email này đã có tài khoản"}
            self.members[email] = {"email": email, "role": role, "pic": pic, "name": body.get("name") or email,
                                   "enc_keys": [], "sign_pub": None, "active": True}
            self.passwords[email] = body["password"]
            return 200, {"ok": True}
        if email not in self.members:
            return 404, {"error": "Không tìm thấy tài khoản"}
        if body["action"] == "reset_password":
            self.passwords[email] = body["password"]
        elif body["action"] == "set_active":
            self.members[email]["active"] = body["active"] is True
            (self.banned.discard if body["active"] else self.banned.add)(email)
        elif body["action"] == "delete":
            self.members.pop(email)
            self.passwords.pop(email, None)
        return 200, {"ok": True}

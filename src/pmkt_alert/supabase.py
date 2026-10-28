"""Team backend on Supabase: sign-in with an emailed 6-digit code, the member list (who is Lead, which PIC),
and the private "reports" bucket. Every rule is enforced by Postgres row-level security (setup_sql), so a
modified app gets nothing more than its own rows and files. Reports stay encrypted and Lead-signed on top."""
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

BUCKET = "reports"


class TeamError(Exception):
    pass


def pic_file(pic: str) -> str:
    """Storage file name of a PIC's part (md5 = the same slug the SQL policy computes; not a secret)."""
    return hashlib.md5(pic.encode("utf-8")).hexdigest() + ".pmkt"


LEAD_FILE = "lead.pmkt"

_SQL = """-- PMKT Alert team setup: run once in Supabase → SQL Editor. Safe to re-run.
create table if not exists public.pmkt_members (
  email text primary key check (email = lower(email)),
  role text not null check (role in ('lead', 'member')),
  pic text,
  name text,
  enc_keys text[] not null default '{}',   -- public encryption keys of the person's devices (set by their app)
  sign_pub text,                            -- Lead only: public signing key, members verify reports with it
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.pmkt_members enable row level security;
revoke all on public.pmkt_members from anon;
grant select, insert, update, delete on public.pmkt_members to authenticated;

create or replace function public.pmkt_is_lead() returns boolean language sql stable security definer
  set search_path = public as $$
  select exists (select 1 from pmkt_members where email = auth.email() and role = 'lead' and active) $$;

create or replace function public.pmkt_my_file() returns text language sql stable security definer
  set search_path = public as $$
  select md5(pic) || '.pmkt' from pmkt_members
  where email = auth.email() and role = 'member' and active and pic is not null $$;

-- A device registers its public keys; a member can never set a signing key or change role / PIC.
create or replace function public.pmkt_register_keys(p_enc text, p_sign text, p_reset boolean default false)
  returns void language plpgsql security definer set search_path = public as $$
begin
  update pmkt_members set
    enc_keys = (select coalesce(array_agg(k order by n), '{}') from (
                  select k, n from unnest(array_remove(enc_keys, p_enc) || p_enc) with ordinality as t(k, n)
                  order by n desc limit 3) last3),
    sign_pub = case when role = 'lead' and p_sign is not null and (sign_pub is null or p_reset) then p_sign
                    else sign_pub end
  where email = auth.email() and active;
end $$;
revoke all on function public.pmkt_register_keys(text, text, boolean) from public, anon;
grant execute on function public.pmkt_register_keys(text, text, boolean) to authenticated;

drop policy if exists pmkt_read on public.pmkt_members;
create policy pmkt_read on public.pmkt_members for select to authenticated
  using (email = auth.email() or (role = 'lead' and active) or public.pmkt_is_lead());
drop policy if exists pmkt_lead_write on public.pmkt_members;
create policy pmkt_lead_write on public.pmkt_members for all to authenticated
  using (public.pmkt_is_lead()) with check (public.pmkt_is_lead());

-- Only emails the Lead added (and still active) can create a login.
create or replace function public.pmkt_only_listed() returns trigger language plpgsql security definer
  set search_path = public as $$
begin
  if not exists (select 1 from pmkt_members where email = lower(new.email) and active) then
    raise exception 'PMKT: email chưa được Lead thêm vào nhóm';
  end if;
  return new;
end $$;
drop trigger if exists pmkt_only_listed on auth.users;
create trigger pmkt_only_listed before insert on auth.users for each row execute function public.pmkt_only_listed();

-- Reports: <report>/lead.pmkt (full, Leads) + <report>/<md5(PIC)>.pmkt (one per PIC, that PIC's members).
insert into storage.buckets (id, name, public) values ('reports', 'reports', false) on conflict do nothing;
drop policy if exists pmkt_reports_read on storage.objects;
create policy pmkt_reports_read on storage.objects for select to authenticated
  using (bucket_id = 'reports' and (public.pmkt_is_lead() or storage.filename(name) = public.pmkt_my_file()));
drop policy if exists pmkt_reports_insert on storage.objects;
create policy pmkt_reports_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'reports' and public.pmkt_is_lead());
drop policy if exists pmkt_reports_delete on storage.objects;
create policy pmkt_reports_delete on storage.objects for delete to authenticated
  using (bucket_id = 'reports' and public.pmkt_is_lead());

-- The first Lead.
insert into public.pmkt_members (email, role, name) values ('LEAD_EMAIL', 'lead', 'Lead')
  on conflict (email) do update set role = 'lead', active = true;
"""


def setup_sql(lead_email: str) -> str:
    email = lead_email.strip().lower()
    if "@" not in email or "'" in email:
        raise TeamError("Email Lead không hợp lệ")
    return _SQL.replace("LEAD_EMAIL", email)


class Supabase:
    """Supabase REST (Auth, PostgREST, Storage) with the user's session token."""

    def __init__(self, url: str, anon: str, opener=urllib.request.urlopen):
        if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
            raise TeamError("Supabase URL phải bắt đầu bằng https://")
        if not anon:
            raise TeamError("Thiếu anon key của Supabase")
        self.url, self.anon, self.opener = url.rstrip("/"), anon, opener
        self.token: str | None = None

    def _call(self, method: str, path: str, body=None, json_body=None, headers=None) -> bytes:
        h = {"apikey": self.anon, "Authorization": f"Bearer {self.token or self.anon}", **(headers or {})}
        data = body
        if json_body is not None:
            data, h["Content-Type"] = json.dumps(json_body).encode(), "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with self.opener(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            try:
                d = json.loads(e.read() or b"{}")
                detail = d.get("msg") or d.get("message") or d.get("error_description") or d.get("error") or ""
            except (ValueError, AttributeError):
                detail = ""
            if "PMKT:" in detail or "Database error saving new user" in detail:
                raise TeamError("Email này chưa được Lead thêm vào nhóm") from None
            if e.code in (401, 403):
                raise TeamError(f"Không có quyền ({detail or e.code}) – thử đăng nhập lại") from None
            raise TeamError(f"Supabase báo lỗi {e.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            raise TeamError(f"Không kết nối được Supabase: {e}") from None

    def _json(self, *a, **k):
        out = self._call(*a, **k)
        return json.loads(out) if out else None

    # -- auth: email + 6-digit code (the Magic Link email template must contain {{ .Token }})
    def send_code(self, email: str) -> None:
        self._call("POST", "/auth/v1/otp", json_body={"email": email.strip().lower(), "create_user": True})

    def verify(self, email: str, code: str) -> str:
        out = self._json("POST", "/auth/v1/verify",
                         json_body={"type": "email", "email": email.strip().lower(), "token": code.strip()})
        self.token = out["access_token"]
        return out["refresh_token"]

    def refresh(self, refresh_token: str) -> str:
        out = self._json("POST", "/auth/v1/token?grant_type=refresh_token", json_body={"refresh_token": refresh_token})
        self.token = out["access_token"]
        return out["refresh_token"]

    def sign_out(self) -> None:
        self._call("POST", "/auth/v1/logout")

    # -- member list (RLS: a member reads itself + Leads; Leads read/write everything)
    def members(self) -> list[dict]:
        return self._json("GET", "/rest/v1/pmkt_members?select=*&order=role,pic,email")

    def member(self, email: str) -> dict | None:
        rows = self._json("GET", f"/rest/v1/pmkt_members?select=*&email=eq.{urllib.parse.quote(email.lower())}")
        return rows[0] if rows else None

    def add_member(self, row: dict) -> dict:
        return self._json("POST", "/rest/v1/pmkt_members", json_body=row, headers={"Prefer": "return=representation"})[0]

    def update_member(self, email: str, fields: dict) -> dict:
        rows = self._json("PATCH", f"/rest/v1/pmkt_members?email=eq.{urllib.parse.quote(email.lower())}",
                          json_body=fields, headers={"Prefer": "return=representation"})
        if not rows:
            raise TeamError("Không có quyền sửa thành viên này")
        return rows[0]

    def delete_member(self, email: str) -> None:
        self._call("DELETE", f"/rest/v1/pmkt_members?email=eq.{urllib.parse.quote(email.lower())}")

    def register_keys(self, enc_pub: str, sign_pub: str | None, reset: bool = False) -> None:
        self._call("POST", "/rest/v1/rpc/pmkt_register_keys", json_body={"p_enc": enc_pub, "p_sign": sign_pub, "p_reset": reset})

    # -- reports (RLS: Leads everything; a member only <report>/<md5(own PIC)>.pmkt)
    def files(self, prefix: str = "") -> list[dict]:
        return self._json("POST", f"/storage/v1/object/list/{BUCKET}",
                          json_body={"prefix": prefix, "limit": 1000, "offset": 0, "sortBy": {"column": "name", "order": "desc"}})

    def reports(self) -> list[str]:
        """Report folders this user can see (a member sees only reports that contain their part), newest first."""
        return sorted({r["name"] for r in self.files() if r.get("id") is None and r.get("name")}, reverse=True)

    def upload(self, path: str, blob: bytes) -> None:
        self._call("POST", f"/storage/v1/object/{BUCKET}/{urllib.parse.quote(path)}", body=blob,
                   headers={"Content-Type": "application/octet-stream", "x-upsert": "false"})

    def download(self, path: str) -> bytes:
        return self._call("GET", f"/storage/v1/object/{BUCKET}/{urllib.parse.quote(path)}")

    def delete_report(self, report: str) -> None:
        files = [f"{report}/{r['name']}" for r in self.files(report + "/") if r.get("id")]
        if files:
            self._call("DELETE", f"/storage/v1/object/{BUCKET}", json_body={"prefixes": files})

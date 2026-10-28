"""Where reports (.pmkt) are uploaded and listed: a shared folder, or Supabase Storage (private bucket).
Files are already encrypted and signed, so the transport only controls who may upload / list / download."""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .package import EXT


class TransportError(Exception):
    pass


class FolderTransport:
    def __init__(self, folder: str):
        self.folder = Path(folder)

    def list(self) -> list[dict]:
        if not self.folder.is_dir():
            raise TransportError(f"Không thấy thư mục chia sẻ: {self.folder}")
        files = sorted(self.folder.glob(f"*{EXT}"), key=lambda f: (f.stat().st_mtime, f.name), reverse=True)
        return [{"name": f.name, "size": f.stat().st_size,
                 "updated": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")} for f in files]

    def upload(self, name: str, blob: bytes) -> None:
        target = self.folder / name
        if target.exists():
            raise TransportError(f"{name} đã tồn tại")
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, target)

    def download(self, name: str) -> bytes:
        return (self.folder / Path(name).name).read_bytes()

    def delete(self, name: str) -> None:
        (self.folder / Path(name).name).unlink(missing_ok=True)


class SupabaseTransport:
    """Supabase Storage REST. Members use the anon key (list/download, allowed by RLS); the Lead logs in
    (email + password) and uploads/deletes with its access token."""

    def __init__(self, url: str, anon: str, bucket: str = "reports", token: str | None = None,
                 opener=urllib.request.urlopen):
        self.url, self.anon, self.bucket, self.token, self.opener = url.rstrip("/"), anon, bucket, token, opener

    def _call(self, method: str, path: str, body=None, json_body=None, headers=None, auth: bool = False):
        h = {"apikey": self.anon, "Authorization": f"Bearer {self.token if auth and self.token else self.anon}",
             **(headers or {})}
        data = body
        if json_body is not None:
            data, h["Content-Type"] = json.dumps(json_body).encode(), "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with self.opener(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read() or b"{}").get("message", "")
            except (ValueError, AttributeError):
                pass
            if e.code in (401, 403):
                raise TransportError(f"Supabase từ chối: không có quyền ({detail or e.code}) – Lead cần đăng nhập lại") from None
            raise TransportError(f"Supabase báo lỗi {e.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            raise TransportError(f"Không kết nối được Supabase: {e}") from None

    def list(self) -> list[dict]:
        rows = json.loads(self._call("POST", f"/storage/v1/object/list/{self.bucket}",
                                     json_body={"prefix": "", "limit": 500, "offset": 0,
                                                "sortBy": {"column": "created_at", "order": "desc"}}))
        return [{"name": r["name"], "size": (r.get("metadata") or {}).get("size"), "updated": r.get("created_at")}
                for r in rows if r.get("name", "").endswith(EXT)]

    def upload(self, name: str, blob: bytes) -> None:
        self._call("POST", f"/storage/v1/object/{self.bucket}/{name}", body=blob, auth=True,
                   headers={"Content-Type": "application/octet-stream", "x-upsert": "false"})

    def download(self, name: str) -> bytes:
        return self._call("GET", f"/storage/v1/object/{self.bucket}/{name}")

    def delete(self, name: str) -> None:
        self._call("DELETE", f"/storage/v1/object/{self.bucket}", json_body={"prefixes": [name]}, auth=True)

    def login(self, email: str, password: str) -> tuple[str, str]:
        out = json.loads(self._call("POST", "/auth/v1/token?grant_type=password",
                                    json_body={"email": email, "password": password}))
        self.token = out["access_token"]
        return out["access_token"], out["refresh_token"]

    def refresh(self, refresh_token: str) -> tuple[str, str]:
        out = json.loads(self._call("POST", "/auth/v1/token?grant_type=refresh_token",
                                    json_body={"refresh_token": refresh_token}))
        self.token = out["access_token"]
        return out["access_token"], out["refresh_token"]


SUPABASE_SQL = """-- PMKT Alert: run once in Supabase → SQL editor (replace the Lead's email)
insert into storage.buckets (id, name, public) values ('reports', 'reports', false) on conflict do nothing;

create policy "pmkt members list and read" on storage.objects for select
  to anon, authenticated using (bucket_id = 'reports');

create policy "pmkt lead uploads" on storage.objects for insert
  to authenticated with check (bucket_id = 'reports' and auth.email() = 'LEAD_EMAIL');

create policy "pmkt lead deletes" on storage.objects for delete
  to authenticated using (bucket_id = 'reports' and auth.email() = 'LEAD_EMAIL');
"""


def make_transport(cfg: dict, token: str | None = None):
    if (cfg or {}).get("type") == "supabase":
        return SupabaseTransport(cfg["url"], cfg["anon"], cfg.get("bucket") or "reports", token)
    if (cfg or {}).get("type") == "folder" and cfg.get("folder"):
        return FolderTransport(cfg["folder"])
    raise TransportError("Chưa cấu hình nơi lưu báo cáo (Cài đặt → Nhóm)")

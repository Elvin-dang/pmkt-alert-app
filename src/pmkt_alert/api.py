"""Everything the UI can call (exposed to JavaScript via pywebview's js_api).
Every public method returns JSON-serializable data and never raises."""
import base64
import functools
import json
import os
import re
import secrets
import threading
import time
import traceback
import urllib.request
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .ai import evaluate_logic, generate, offline, pic_rows, planned_calls
from .aggregate import asin_map
from .changelog import bundled_text, parse as parse_changelog
from .backtest import apply_approved, propose_from_feedback, proposals_from_review
from .claude import ClaudeError, ask, cancel_all, check_status, grounded, open_login
from .claude import _exe as claude_exe
from .claude import install as install_claude_cli
from .evidence import evidence
from .export import export_pic
from .identity import LeadKeys, MemberKey, protect, raw_public, unprotect
from .package import EXT, PackageError
from .package import build as build_package
from .package import read as read_package
from .progress import Eta
from .share import build_parts, unpack_run
from .supabase import LEAD_FILE, Supabase, TeamError, pic_file
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


EMAIL_RE = re.compile(r"[^@\s']+@[^@\s']+\.[^@\s']+")
_pub64 = lambda pub: base64.b64encode(raw_public(pub)).decode()  # noqa: E731


def _new_password() -> str:
    """Readable first password, e.g. 'kq7m-x3vt-p9da' (no 0/o/1/l)."""
    abc = "abcdefghijkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(abc) for _ in range(4)) for _ in range(3))


def _bundled_team() -> dict:
    """Optional team.json shipped in the release build (Supabase URL + anon key – public by design)."""
    p = Path(__file__).with_name("team.json")
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def _kdf(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))
from .loaders import ROLES, TRACKER_REQUIRED, TRACKER_SHEETS, InputError, detect_inputs, input_files, load_inputs, role_of
from .logic import LogicError, load_logic, version_from_name
from .pipeline import result_to_json, run_rules
from .prompts import STYLE_SCHEMA, TEAM_SCHEMA, style_prompt, team_prompt
from .scorecard import METRICS, scorecard, weekly
from .rules.actions import suggest_email_map
from .store import Store
from .updater import DEFAULT_REPO, apply_update, download_verified, is_newer, latest_release, recent_releases
from .windows import Windows


STOPPED = "Đã dừng theo yêu cầu"


def always_fail(prompt, schema):
    raise ClaudeError("Claude Code chưa sẵn sàng")


LEAD_ONLY = "Chỉ Lead được làm việc này – bạn đang ở chế độ Thành viên (chỉ xem)"
MEMBER_SETTINGS = {"language", "ui_lang", "auto_update_check", "last_seen_version"}


def lead_only(fn):
    """Refused in Member mode (enforced here, not only hidden in the UI)."""
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        if self._role() == "member":
            raise PermissionError(LEAD_ONLY)
        return fn(self, *a, **k)
    return wrapper


def safe(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except (InputError, LogicError, ClaudeError, ValueError, RuntimeError, PermissionError, PackageError, TeamError) as e:
            return {"error": str(e)}
        except Exception as e:  # never let a traceback reach the UI
            self._log(traceback.format_exc())
            return {"error": f"Lỗi không mong đợi: {e} (chi tiết: {self._store.base / 'error.log'})"}
    return wrapper


class Api:
    def __init__(self, store: Store, ask_fn=ask, status_fn=check_status, release_fn=latest_release,
                 recent_fn=recent_releases, sb_opener=urllib.request.urlopen):
        self._store, self._status = store, status_fn
        self._ask = self._with_note(ask_fn)
        self._release, self._recent = release_fn, recent_fn
        self._window = None
        self._cancel = threading.Event()  # set by cancel_run(); cleared when a run ends
        self._running = False
        self._inputs = None
        self._paths: list[str] = []
        self._eta: Eta | None = None  # time-left estimate of the run in progress
        self._member: dict | None = None  # Member mode: the opened .pmkt (run, inputs, logic path, file)
        self._sb_opener, self._sb_cache = sb_opener, None  # Supabase HTTP opener (tests: a fake), signed-in client
        self._startup_file: str | None = None  # a .pmkt double-clicked to start the app

    # ------------------------------------------------------------- helpers
    def _with_note(self, ask_fn):
        """Every Claude request starts with the user's note from Settings."""
        def ask_with_note(prompt: str, schema: dict) -> dict:
            note = (self._store.get_settings().get("claude_note") or "").strip()
            prefix = f"GHI CHÚ CỦA NGƯỜI DÙNG (bắt buộc tuân theo, ưu tiên hơn mọi gợi ý khác):\n{note}\n\n" if note else ""
            return ask_fn(prefix + prompt, schema)
        return ask_with_note

    def _log(self, text: str) -> None:
        with open(self._store.base / "error.log", "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat()}\n{text}\n")

    def _progress(self, step: str, state: str, detail: str = "", call_finished: bool = False) -> None:
        eta = self._eta
        if eta is not None:
            if call_finished:
                eta.calls_done()
            elif ":" not in step and step != "review":
                (eta.start if state == "running" else eta.done)(step)
        if self._window is not None:
            extra = {"eta": round(eta.remaining()) if eta else None}
            self._window.evaluate_js(f"window.onProgress && onProgress({json.dumps(step)}, {json.dumps(state)}, "
                                     f"{json.dumps(detail)}, {json.dumps(extra)})")

    # ------------------------------------------------------------- team (Supabase) & sharing
    def _role(self) -> str | None:
        return self._store.get_settings().get("role")

    def _team(self) -> dict:
        return self._store.get_settings().get("team") or {}

    def _secrets(self) -> dict:
        p = self._store.base / "secrets.bin"
        return json.loads(unprotect(p.read_bytes())) if p.exists() else {}

    def _save_secrets(self, d: dict) -> None:
        p = self._store.base / "secrets.bin"
        p.write_bytes(protect(json.dumps(d).encode("utf-8")))
        try:
            p.chmod(0o600)
        except OSError:
            pass

    def _keys(self, email: str | None = None) -> dict:
        return (self._secrets().get("keys") or {}).get(email or self._team().get("email") or "", {})

    def _save_keys(self, email: str, keys: dict) -> None:
        sec = self._secrets()
        sec.setdefault("keys", {})[email] = keys
        self._save_secrets(sec)

    def _lead_keys(self) -> LeadKeys:
        raw = self._keys().get("lead")
        if not raw:
            raise PermissionError("Máy này chưa có khoá Lead – nhập file khoá Lead hoặc tạo khoá mới (Cài đặt → Nhóm)")
        return LeadKeys.from_bytes(base64.b64decode(raw))

    def _my_reader_key(self):
        if self._role() == "lead":
            return self._lead_keys().enc_private
        raw = self._keys().get("member")
        if not raw:
            raise PermissionError("Chưa đăng nhập nhóm (Cài đặt → Nhóm)")
        return MemberKey.from_bytes(base64.b64decode(raw)).private

    def _server(self) -> tuple[str, str]:
        t, b = self._team(), _bundled_team()
        return (t.get("url") or b.get("url") or "", t.get("anon") or b.get("anon") or "")

    def _sb(self) -> Supabase:
        """Signed-in client; the access token is refreshed at most every 45 minutes."""
        sb_cfg = self._server()
        if self._sb_cache and self._sb_cache[0] == sb_cfg and time.monotonic() - self._sb_cache[1] < 45 * 60:
            return self._sb_cache[2]
        session = self._secrets().get("session")
        if not session or not sb_cfg[0]:
            raise PermissionError("Chưa đăng nhập nhóm (Cài đặt → Nhóm)")
        sb = Supabase(*sb_cfg, opener=self._sb_opener)
        try:
            new_rt = sb.refresh(session["refresh"])
        except TeamError as e:
            raise PermissionError(f"Phiên đăng nhập đã hết hạn – đăng nhập lại ({e})") from None
        self._save_secrets({**self._secrets(), "session": {**session, "refresh": new_rt}})
        self._sb_cache = (sb_cfg, time.monotonic(), sb)
        return sb

    def _lead_signs(self, sb: Supabase | None = None) -> list:
        """Public signing keys of the active Leads (members may read Lead rows); cached for offline file opens."""
        try:
            sb = sb or self._sb()
            signs = [r["sign_pub"] for r in sb.members() if r["role"] == "lead" and r["active"] and r.get("sign_pub")]
            self._store.save_settings({"team": {**self._team(), "lead_signs": signs}})
        except (PermissionError, TeamError):
            signs = self._team().get("lead_signs") or []
        return [Ed25519PublicKey.from_public_bytes(base64.b64decode(x)) for x in signs]

    def _register_device(self, sb: Supabase, row: dict, email: str) -> bool:
        """Create/keep this device's keys and publish their public halves. Returns needs_key (Lead without the
        signing key the team trusts: import the Lead key file or reset it)."""
        keys = self._keys(email)
        if row["role"] == "lead":
            if not keys.get("lead"):
                if row.get("sign_pub"):
                    return True
                keys = {**keys, "lead": base64.b64encode(LeadKeys.new().to_bytes()).decode()}
                self._save_keys(email, keys)
            lead = LeadKeys.from_bytes(base64.b64decode(keys["lead"]))
            sign = _pub64(lead.sign_public)
            if row.get("sign_pub") not in (None, sign):
                return True
            sb.register_keys(_pub64(lead.enc_public), sign)
            return False
        if not keys.get("member"):
            keys = {**keys, "member": base64.b64encode(MemberKey.new().to_bytes()).decode()}
            self._save_keys(email, keys)
        sb.register_keys(_pub64(MemberKey.from_bytes(base64.b64decode(keys["member"])).public), None)
        return False

    def _open_blob(self, blob: bytes, name: str) -> dict:
        key, err = self._my_reader_key(), None
        for sign in self._lead_signs():
            try:
                meta, files = read_package(blob, key, sign)
                break
            except PackageError as e:
                err = e
                if "chữ ký" not in str(e):
                    raise
        else:
            raise err or PackageError("Chưa có khoá ký của Lead – đăng nhập nhóm trước")
        run, inputs, logic_bytes, logic_name = unpack_run(files)
        logic_path = self._store.base / "shared" / logic_name
        logic_path.parent.mkdir(parents=True, exist_ok=True)
        logic_path.write_bytes(logic_bytes)
        if self._role() == "member":
            self._member = {"run": {**run, "file": name, "published_by": meta.get("by"), "published_at": meta.get("at"),
                                    "as_of_meta": meta.get("as_of")}, "inputs": inputs, "logic_path": logic_path}
            return self._member
        return {"run": {**run, "file": name, "published_by": meta.get("by"), "published_at": meta.get("at")}}

    def _report_path(self, name: str) -> str:
        if self._role() == "lead":
            return f"{name}/{LEAD_FILE}"
        return f"{name}/{pic_file(self._team().get('pic') or '')}"

    def _member_state(self) -> dict:
        if self._member:
            return self._member
        reports = self._sb().reports()
        if not reports:
            raise ValueError("Chưa có báo cáo nào – chờ Lead tải lên")
        return self._open_blob(self._sb().download(self._report_path(reports[0])), reports[0])

    @safe
    def team_info(self) -> dict:
        t, st = self._team(), self._store.get_settings()
        url, anon = self._server()
        out = {"url": url, "configured": bool(url and anon), "bundled": bool(_bundled_team()), "signed_in": bool(self._secrets().get("session")), "role": st.get("role"),
               **{k: t.get(k) for k in ("email", "pic", "name")}, "needs_key": bool(t.get("needs_key"))}
        if self._member:
            out["opened"] = {k: self._member["run"].get(k) for k in ("file", "published_by", "published_at")}
        return out

    @safe
    def team_connect(self, url: str = "", anon: str = "") -> dict:
        bundled = _bundled_team()
        t = self._team()
        url = (url or t.get("url") or bundled.get("url") or "").strip()
        anon = (anon or (t.get("anon") if url == t.get("url") else None) or bundled.get("anon") or "").strip()
        Supabase(url, anon)  # validates
        self._store.save_settings({"team": {**self._team(), "url": url, "anon": anon}})
        self._sb_cache = None
        return self.team_info()

    @safe
    def team_sign_in(self, email: str, password: str) -> dict:
        url, anon = self._server()
        if not url:
            raise ValueError("App chưa có máy chủ nhóm – cập nhật app lên bản mới nhất")
        email = email.strip().lower()
        sb = Supabase(url, anon, opener=self._sb_opener)
        refresh = sb.sign_in(email, password)
        row = sb.member(email)
        if not row or not row["active"]:
            raise PermissionError("Tài khoản này chưa được Lead kích hoạt")
        self._save_secrets({**self._secrets(), "session": {"email": email, "refresh": refresh}})
        self._sb_cache = ((url, anon), time.monotonic(), sb)
        needs_key = self._register_device(sb, row, email)
        self._member = None
        self._store.save_settings({"role": row["role"], "team": {**self._team(), "email": email, "pic": row.get("pic"),
                                                                  "name": row.get("name"), "needs_key": needs_key}})
        self._lead_signs(sb)
        return self.team_info()

    @safe
    def team_change_password(self, password: str) -> dict:
        if len(password or "") < 10:
            raise ValueError("Mật khẩu cần ít nhất 10 ký tự")
        self._sb().change_password(password)
        return {"ok": True}

    @safe
    def team_sign_out(self) -> dict:
        try:
            self._sb().sign_out()
        except (PermissionError, TeamError):
            pass
        sec = self._secrets()
        sec.pop("session", None)
        self._save_secrets(sec)
        self._sb_cache, self._member = None, None
        self._store.save_settings({"role": None})
        return self.team_info()

    @safe
    @lead_only
    def members(self) -> dict:
        rows = self._sb().members()
        for r in rows:
            r["status"] = "disabled" if not r["active"] else "ready" if r.get("enc_keys") else "invited"
            r.pop("enc_keys", None)
        return {"members": rows}

    @safe
    @lead_only
    def add_member(self, email: str, name: str, pic: str, role: str = "member") -> dict:
        """Create a login + member row (inside Supabase). Returns the first password for the Lead to hand over."""
        email = email.strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise ValueError("Email không hợp lệ")
        if role not in ("lead", "member") or (role == "member" and not pic.strip()):
            raise ValueError("Thành viên cần có PIC")
        password = _new_password()
        self._sb().admin("create", email=email, name=name.strip() or email, role=role,
                         pic=pic.strip() if role == "member" else None, password=password)
        return {**self.members(), "password": password}

    @safe
    @lead_only
    def reset_password(self, email: str) -> dict:
        password = _new_password()
        self._sb().admin("reset_password", email=email, password=password)
        return {"password": password}

    @safe
    @lead_only
    def update_member(self, email: str, fields: dict) -> dict:
        sb = self._sb()
        if "active" in fields:
            sb.admin("set_active", email=email, active=bool(fields["active"]))
        clean = {k: v for k, v in fields.items() if k in ("pic", "name", "role")}
        if clean:
            sb.update_member(email, clean)
        return self.members()

    @safe
    @lead_only
    def remove_member(self, email: str) -> dict:
        self._sb().admin("delete", email=email)
        return self.members()

    @safe
    @lead_only
    def upload_report(self, run_id: str | None = None) -> dict:
        """Lead, after reviewing a run: one file per PIC (encrypted for that PIC's members) + the full file for
        Leads, all signed, uploaded under PMKT-Alert_<date>_<time>/."""
        sb = self._sb()
        lead = self._lead_keys()
        me = sb.member(self._team().get("email") or "")
        if not me or me.get("sign_pub") != _pub64(lead.sign_public):
            raise PermissionError("khoá Lead trên máy này không còn là khoá của nhóm – nhập file khoá Lead mới")
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        rows = [r for r in sb.members() if r["active"]]
        pub = lambda k: X25519PublicKey.from_public_bytes(base64.b64decode(k))  # noqa: E731
        readers: dict[str, list] = {}
        counts: dict[str, int] = {}
        for r in rows:
            if r["role"] == "member" and r.get("pic") and r.get("enc_keys"):
                readers.setdefault(r["pic"], []).extend(pub(k) for k in r["enc_keys"])
                counts[r["pic"]] = counts.get(r["pic"], 0) + 1
        other_leads = [pub(k) for r in rows if r["role"] == "lead" for k in r.get("enc_keys") or []
                       if k != _pub64(lead.enc_public)]
        logic_path = next((p for v, p in self._store.logic_versions() if v == run["result"]["logic_version"]),
                          self._store.active_logic())
        sc = scorecard(run["result"], self._store.get_settings().get("score_weights") or {})
        parts = build_parts(run, self._ensure_inputs(), logic_path, list(readers), {p["pic"]: p for p in sc["pics"]})
        now = datetime.now()
        meta = {"by": self._team().get("name") or "Lead", "at": now.isoformat(timespec="seconds"),
                "as_of": run["result"]["as_of"], "app": __version__}
        name = f"PMKT-Alert_{now:%Y-%m-%d_%H-%M}"
        if name in set(sb.reports()):
            name = f"PMKT-Alert_{now:%Y-%m-%d_%H-%M-%S}"
        size = 0
        for path, part, who in [(LEAD_FILE, "lead", other_leads)] + [(pic_file(p), f"pic:{p}", readers[p]) for p in readers]:
            blob = build_package({part: (parts[part], who)}, meta, lead)
            sb.upload(f"{name}/{path}", blob)
            size += len(blob)
        pics = {d["pic"] for d in run["result"]["digest"]}
        self._store.save_run_field(run["run_id"], "uploaded", (run.get("uploaded") or []) + [name])
        waiting = sorted(r["email"] for r in rows if r["role"] == "member" and not r.get("enc_keys"))
        return {"name": name, "size": size, "readers": counts, "no_readers": sorted(pics - set(counts)), "waiting": waiting}

    @safe
    def list_reports(self) -> dict:
        return {"reports": [{"name": n} for n in self._sb().reports()]}

    @safe
    def open_report(self, name: str) -> dict:
        return self._open_blob(self._sb().download(self._report_path(name)), name)["run"]

    @safe
    @lead_only
    def delete_report(self, name: str) -> dict:
        self._sb().delete_report(name)
        return {"ok": True}

    @safe
    @lead_only
    def export_lead_key(self, path: str | None, password: str) -> dict:
        if len(password or "") < 8:
            raise ValueError("Mật khẩu file khoá cần ít nhất 8 ký tự")
        raw = self._lead_keys().to_bytes()
        if not path:
            import webview
            picked = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename="PMKT-Lead.pmktkey")
            if not picked:
                return {"cancelled": True}
            path = picked if isinstance(picked, str) else picked[0]
        payload = json.dumps({"keys": base64.b64encode(raw).decode(), "email": self._team().get("email")}).encode()
        salt, nonce = os.urandom(16), os.urandom(12)
        Path(path).write_bytes(b"PMKTKEY3" + salt + nonce + AESGCM(_kdf(password, salt)).encrypt(nonce, payload, b"PMKTKEY3"))
        return {"path": str(path)}

    @safe
    def import_lead_key(self, path: str, password: str) -> dict:
        blob = Path(path).read_bytes()
        if not blob.startswith(b"PMKTKEY3"):
            raise ValueError("Không phải file khoá Lead (.pmktkey) của phiên bản này")
        try:
            d = json.loads(AESGCM(_kdf(password, blob[8:24])).decrypt(blob[24:36], blob[36:], b"PMKTKEY3"))
        except Exception:
            raise ValueError("Sai mật khẩu file khoá") from None
        if self._role() != "lead":
            raise PermissionError("Đăng nhập bằng tài khoản Lead trước khi nhập khoá")
        email = self._team()["email"]
        self._save_keys(email, {**self._keys(email), "lead": d["keys"]})
        sb = self._sb()
        needs = self._register_device(sb, sb.member(email), email)
        self._store.save_settings({"team": {**self._team(), "needs_key": needs}})
        if needs:
            raise ValueError("File khoá này không phải khoá hiện tại của nhóm")
        return self.team_info()

    @safe
    @lead_only
    def team_reset_lead_key(self) -> dict:
        """New signing key for the team (lost key file). Reports signed with the old key no longer open."""
        if self._role() != "lead":
            raise PermissionError(LEAD_ONLY)
        email = self._team()["email"]
        lead = LeadKeys.new()
        self._save_keys(email, {**self._keys(email), "lead": base64.b64encode(lead.to_bytes()).decode()})
        sb = self._sb()
        sb.register_keys(_pub64(lead.enc_public), _pub64(lead.sign_public), reset=True)
        self._store.save_settings({"team": {**self._team(), "needs_key": False}})
        self._lead_signs(sb)
        return self.team_info()

    @safe
    def pick_file(self, label: str, pattern: str) -> dict:
        if self._window is None:
            raise RuntimeError("Chưa mở cửa sổ app")
        import webview
        picked = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=(f"{label} ({pattern})",))
        return {"path": (picked[0] if isinstance(picked, (list, tuple)) else picked) if picked else None}

    @safe
    def startup_open(self) -> dict:
        """Open the .pmkt the app was launched with (double-click), once."""
        path, self._startup_file = self._startup_file, None
        if not path:
            return {"opened": None}
        run = self._open_blob(Path(path).read_bytes(), Path(path).name)["run"]
        return {"opened": {k: run.get(k) for k in ("file", "published_by", "published_at")}}

    @safe
    def open_local_report(self, path: str) -> dict:
        return self._open_blob(Path(path).read_bytes(), Path(path).name)["run"]

    def _latest(self) -> dict:
        if self._role() == "member":
            return self._member_state()["run"]
        runs = self._store.list_runs()
        if not runs:
            raise ValueError("Chưa có lần chạy nào")
        return self._store.load_run(runs[0]["run_id"])

    def _logic(self):
        """Active logic; problems in it fall back to the newest other stored version that loads cleanly."""
        active = self._store.active_logic()
        if not active:
            raise ValueError("Chưa có file Alert_Logic")
        fallback = None
        for _, p in reversed(self._store.logic_versions()):
            if p != active:
                cand = load_logic(p)
                if not any(i["hint"] == "error" for i in cand.issues):
                    fallback = cand
                    break
        return load_logic(active, fallback=fallback)

    def _ensure_inputs(self):
        if self._role() == "member":
            return self._member_state()["inputs"]
        if self._inputs is None:
            paths = self._paths or self._store.get_settings().get("last_inputs", {}).get("paths", [])
            if not paths:
                raise ValueError("Chưa chọn file data")
            self._paths = paths
            self._inputs = load_inputs(detect_inputs([Path(p) for p in paths]), self._store.get_settings().get("ads_account") or None)
        return self._inputs

    def _repo(self) -> str:
        return self._store.get_settings().get("github_repo") or DEFAULT_REPO

    # ------------------------------------------------------------- run
    @safe
    def pick_folder(self) -> dict:
        if self._window is None:
            raise RuntimeError("Chưa mở cửa sổ app")
        import webview
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return {"paths": list(picked) if picked else []}

    @safe
    def pick_files(self) -> dict:
        if self._window is None:
            raise RuntimeError("Chưa mở cửa sổ app")
        import webview
        picked = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                 file_types=("Excel / CSV (*.xlsx;*.xlsm;*.csv)",))
        return {"paths": list(picked) if picked else []}

    def _on_drop(self, event: dict) -> None:
        """Native drop handler (registered in app.py): only Python sees the dropped files' full paths."""
        files = (event.get("dataTransfer") or {}).get("files", [])
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths and self._window is not None:
            self._window.evaluate_js(f"window.onDropPaths && onDropPaths({json.dumps(paths)})")

    @safe
    def detect(self, paths: list[str]) -> dict:
        """Classify picked files/folders (.xlsx or .csv). Earlier paths win per role, so the UI sends new picks
        first; inside a folder the newest file wins. The Tracking slot is one workbook or its CSV tables
        (raw_sso_us, Product Info, KPI[, INELIGIBLE ASIN]). Partial picks are fine: missing roles are listed."""
        files: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                files += sorted(input_files([p]), key=lambda f: f.stat().st_mtime, reverse=True)
            elif p.exists():
                files.append(p)
        found, unknown = {}, []
        for f in files:
            try:
                role = role_of(f)
            except Exception:
                role = None
            if role is None:
                unknown.append(f.name)
            elif role not in found:
                found[role] = f
        info = lambda f: {"path": str(f), "name": f.name, "size_mb": round(f.stat().st_size / 1e6, 1)}  # noqa: E731
        roles = {r: info(f) for r, f in found.items() if r in ROLES}
        parts = {t: found[t] for t in TRACKER_SHEETS if t in found}
        tracker_missing = []
        if parts and "tracker" not in roles:
            tracker_missing = [TRACKER_SHEETS[t] for t in TRACKER_REQUIRED if t not in parts]
            if not tracker_missing:
                roles["tracker"] = {"path": str(parts["raw"]), "paths": [str(f) for f in parts.values()],
                                    "name": " + ".join(f.name for f in parts.values()),
                                    "size_mb": round(sum(f.stat().st_size for f in parts.values()) / 1e6, 1)}
        elif parts and "tracker" in roles:  # CSV tables override the workbook's sheets
            roles["tracker"]["paths"] = [roles["tracker"]["path"], *[str(f) for f in parts.values()]]
        return {"roles": roles, "missing": [r for r in ROLES if r not in roles], "unknown": unknown,
                "tracker_missing": tracker_missing}

    @safe
    def cancel_run(self) -> dict:
        if not self._running:
            return {"ok": False}
        self._cancel.set()
        cancel_all()
        return {"ok": True}

    @safe
    @lead_only
    def run(self, paths: list[str], as_of: str | None = None, use_claude: bool = True) -> dict:
        self._running = True
        self._eta = Eta(self._store.get_settings().get("step_times"))
        self._eta.plan(["load", "logic", "rules"] + (["claude", "logic_eval"] if use_claude else []), claude_calls=0)
        try:
            return self._run(paths, as_of, use_claude)
        finally:
            self._store.save_settings({"step_times": self._eta.learned()})
            self._eta = None
            self._running = False
            self._cancel.clear()

    def _ask_unless_stopped(self, prompt: str, schema: dict) -> dict:
        if self._cancel.is_set():
            raise ClaudeError(STOPPED)
        return self._ask(prompt, schema)

    def _run(self, paths: list[str], as_of: str | None, use_claude: bool) -> dict:
        self._progress("load", "running", "Đọc & làm sạch data")
        roles = detect_inputs([Path(p) for p in paths])
        inputs = load_inputs(roles, self._store.get_settings().get("ads_account") or None)
        self._inputs, self._paths = inputs, [str(p) for p in paths]
        self._store.save_settings({"last_inputs": {"paths": self._paths}})
        # The picked logic file is used unless an identical copy is already stored (then the active
        # version stays, e.g. a Ver N+1 the app created from approved proposals).
        picked = roles["logic"]
        same = self._store.base / "logic" / picked.name
        if not (same.exists() and same.read_bytes() == picked.read_bytes()):
            self._store.import_logic(picked)  # problems inside it are reported, never block the run
        logic = self._logic()
        rank = {"error": 0, "warn": 1, "info": 2}
        logic_issues = sorted(logic.issues, key=lambda i: rank[i["hint"]])
        errs = sum(i["hint"] == "error" for i in logic_issues)
        self._eta.start("logic")
        self._progress("logic", "warn" if errs else "done",
                       f"{logic.path.name}: {errs} lỗi (đã dùng giá trị dự phòng), "
                       f"{sum(i['code'] == 'UNUSED' for i in logic_issues)} tham số app chưa dùng" if logic_issues else logic.path.name)
        if self._cancel.is_set():
            self._progress("load", "warn", "Đã dừng")
            return {"cancelled": True}
        self._progress("load", "done", f"{len(inputs.raw):,} dòng raw · {len(inputs.ads):,} dòng ads_camp")

        self._progress("rules", "running", "Tầng 0–4")
        result = run_rules(inputs, logic, date.fromisoformat(as_of) if as_of else None)
        rj = result_to_json(result)
        rj["logic_issues"] = logic_issues
        rj["logic_file"] = logic.path.name
        rj["inputs"] = {
            "raw": {"rows": len(inputs.raw), "last": str(inputs.raw["date"].max())},
            "ads": {"rows": len(inputs.ads), "last": str(inputs.ads["date"].max()),
                    "account": inputs.ads.attrs.get("account"), "accounts": inputs.ads.attrs.get("accounts", [])},
            "activity": {"rows": len(inputs.activity), "users": int(inputs.activity["user"].nunique())},
            "files": {r: p.name for r, p in roles.items()},
        }
        run_id = self._store.save_run(rj, None)
        self._progress("rules", "done", f"{len(rj['pl'])} PL · {len(rj['camp'])} campaign")
        ai = None
        status = self._status() if use_claude else None
        if use_claude and status.level != "ok":
            ai = offline(rj, status.error or "Claude Code chưa sẵn sàng")
            ai["logic_eval"] = evaluate_logic(logic_issues, logic, ask_fn=always_fail)
            self._store.update_run_ai(run_id, ai)
            self._progress("claude", "warn", ai["error"])
            self._eta.done("logic_eval")
        elif use_claude:
            careful = bool(self._store.get_settings().get("careful_mode", True))
            self._eta.calls_total = self._eta.calls_left = planned_calls(rj, careful)
            self._progress("claude", "running", "5 bước/PIC: dữ kiện → nháp → kiểm tra → biên tập → kiểm tra lại"
                           if careful else "Chế độ nhanh: nháp → kiểm tra")
            amap = asin_map(inputs.products, result.as_of)
            l7d = Windows(result.as_of).l7d
            inel = inputs.ineligible[(inputs.ineligible["date"] >= l7d[0]) & (inputs.ineligible["date"] <= l7d[1])]
            inel = inel.merge(amap, on="asin")[["asin", "pl", "pic", "reason"]].drop_duplicates("asin")
            ai = generate(rj, logic, self._store, inputs.event_days, inputs.defind_text,
                          inel.to_dict("records"), ask_fn=self._ask_unless_stopped, careful=careful,
                          on_step=self._progress)
            if self._cancel.is_set():
                ai.update(claude_ok=False, error=STOPPED + " – kết quả rule vẫn đầy đủ",
                          logic_eval=evaluate_logic(logic_issues, logic, ask_fn=always_fail))
                self._store.update_run_ai(run_id, ai)
                self._progress("claude", "warn", "Đã dừng")
                return {"run_id": run_id, "result": rj, "ai": ai, "stopped": True, "published": None}
            self._eta.done("claude")
            self._progress("logic_eval", "running", "Claude đánh giá các vấn đề trong file logic")
            ai["logic_eval"] = evaluate_logic(logic_issues, logic, ask_fn=self._ask)
            self._progress("logic_eval", "done", ai["logic_eval"]["summary"][:120])
            self._store.update_run_ai(run_id, ai)
            try:
                proposals_from_review(ai["review"], logic, self._store, inputs, result.as_of)
            except Exception:  # a failed backtest must not hide the run
                self._log(traceback.format_exc())
            self._progress("claude", "done" if ai["claude_ok"] else "warn", ai["error"] or "")
        return {"run_id": run_id, "result": rj, "ai": ai, "stopped": False, "published": None}

    @safe
    def evidence(self, unit_id: str, run_id: str | None = None) -> dict:
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        rj = run["result"]
        logic_path = (self._member_state()["logic_path"] if self._role() == "member" else
                      next((p for v, p in self._store.logic_versions() if v == rj["logic_version"]), None)
                      or self._store.active_logic())
        ev = evidence(self._ensure_inputs(), load_logic(logic_path), rj, unit_id)
        return {**ev, "files": rj.get("inputs", {}).get("files", {}), "logic_file": Path(logic_path).name,
                "as_of": rj["as_of"]}

    def _run_or_latest(self, run_id: str | None) -> dict:
        if self._role() == "member":
            return self._latest()
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        return run

    def _runs_history(self) -> list[dict]:
        if self._role() == "member":
            res = self._latest()["result"]
            return [{"run_id": self._latest().get("file"), "as_of": res.get("as_of"),
                     "by_pic": {d["pic"]: {"high": d["pl_high"] + d["camp_high"], "excess": round(d["excess_new"], 2)}
                                for d in res.get("digest", [])}}]
        out = []
        for r in reversed(self._store.list_runs()[:30]):
            res = (self._store.load_run(r["run_id"]).get("result") or {})
            out.append({"run_id": r["run_id"], "as_of": res.get("as_of"),
                        "by_pic": {d["pic"]: {"high": d["pl_high"] + d["camp_high"], "excess": round(d["excess_new"], 2)}
                                   for d in res.get("digest", [])}})
        return out

    @safe
    def dashboard(self, run_id: str | None = None) -> dict:
        run = self._run_or_latest(run_id)
        weights = self._store.get_settings().get("score_weights") or {}
        sc = scorecard(run["result"], weights)
        if self._role() == "member":  # the shared part only carries this PIC; scores come from the Lead's full run
            sc["pics"] = [run["my_scorecard"]] if run.get("my_scorecard") else []
        return {"run_id": run["run_id"], "scorecard": sc,
                "weekly": weekly(self._ensure_inputs(), date.fromisoformat(run["result"]["as_of"])),
                "runs": self._runs_history(), "team_review": run.get("team_review")}

    @safe
    @lead_only
    def save_score_weights(self, weights: dict) -> dict:
        keys = {m["key"] for m in METRICS}
        clean = {k: max(0.0, float(v)) for k, v in weights.items() if k in keys}
        self._store.save_settings({"score_weights": clean})
        return {"weights": clean}

    @safe
    @lead_only
    def team_review(self, run_id: str | None = None) -> dict:
        run = self._run_or_latest(run_id)
        sc = scorecard(run["result"], self._store.get_settings().get("score_weights") or {})
        wk = weekly(self._ensure_inputs(), date.fromisoformat(run["result"]["as_of"]))
        hist = self._runs_history()
        out = self._ask(team_prompt(sc, wk, hist), TEAM_SCHEMA)
        facts = [{**p["values"], **{f"score_{k}": v for k, v in p["scores"].items()}, "total": p["total"],
                  "rank": p["rank"]} for p in sc["pics"]] + wk + [{"time_gone": sc["time_gone"]}]
        facts += [v for h in hist for v in h["by_pic"].values()]
        dropped = 0
        if not grounded(out["summary"], facts):
            out["summary"], dropped = "", dropped + 1
        for key, fields in (("highlights", ("text",)), ("improve", ("text", "suggestion"))):
            kept = [x for x in out[key] if all(grounded(x.get(f, ""), facts) for f in fields)]
            dropped += len(out[key]) - len(kept)
            out[key] = kept
        review = {**out, "dropped": dropped, "created": datetime.now().isoformat(timespec="seconds")}
        self._store.save_run_field(run["run_id"], "team_review", review)
        return review

    @safe
    def results(self, run_id: str | None = None) -> dict:
        if self._role() == "member":
            return self.open_report(run_id) if run_id else self._latest()
        return self._store.load_run(run_id) if run_id else self._latest()

    @safe
    def claude_status(self) -> dict:
        return self._status().to_dict()

    @safe
    def install_claude(self) -> dict:
        out = install_claude_cli()
        return {**out, "status": self._status().to_dict()}

    @safe
    def open_claude_login(self) -> dict:
        exe = claude_exe()
        if not exe:
            raise RuntimeError("Chưa cài Claude Code")
        open_login(exe)
        return {"ok": True}

    # ------------------------------------------------------------- feedback & review
    @safe
    @lead_only
    def submit_feedback(self, item: dict) -> dict:
        run = self._store.load_run(item["run_id"]) if item.get("run_id") else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        rows = {r["unit_id"]: r for r in run["result"]["pl"] + run["result"]["camp"]}
        row = rows.get(item.get("unit_id"), {})
        fid = self._store.add_feedback({**item, "run_id": run["run_id"],
                                        "logic_version": run["result"]["logic_version"], "row": row})
        fb = next(f for f in self._store.list_feedback() if f["id"] == fid)
        try:
            out = propose_from_feedback(fb, row, self._logic(), self._store, self._ensure_inputs(),
                                        date.fromisoformat(run["result"]["as_of"]), ask_fn=self._ask)
        except ClaudeError as e:
            return {"feedback_id": fid, "error": f"Đã lưu góp ý, nhưng Claude chưa phân tích được: {e}"}
        return {"feedback_id": fid, **out}

    @safe
    def review(self) -> dict:
        if self._role() == "member":
            run = self._latest()
        else:
            runs = self._store.list_runs()
            run = self._store.load_run(runs[0]["run_id"]) if runs else {}
        res, ai = run.get("result") or {}, run.get("ai") or {}
        issues = res.get("logic_issues") or []
        logic_eval = ai.get("logic_eval")
        if issues and not logic_eval:  # run without Claude: still show rule-based verdicts
            logic_eval = evaluate_logic(issues, load_logic(self._store.active_logic()), ask_fn=always_fail)
        return {"findings": ai.get("review") or [], "proposals": self._store.proposals(),
                "feedback": self._store.list_feedback(), "logic_issues": issues, "logic_eval": logic_eval,
                "logic_file": res.get("logic_file")}

    @safe
    @lead_only
    def set_proposal(self, pid: str, status: str) -> dict:
        if status not in ("approved", "rejected", "pending"):
            raise ValueError("Trạng thái không hợp lệ")
        self._store.set_proposal_status(pid, status)
        return {"proposals": self._store.proposals()}

    @safe
    @lead_only
    def apply_proposals(self) -> dict:
        out = apply_approved(self._store, self._logic())
        self._ensure_inputs()
        run = self.run(self._paths)
        return {**run, "logic_file": out.name}

    # ------------------------------------------------------------- lessons & history
    @safe
    def lessons(self) -> dict:
        return {"lessons": self._store.lessons()}

    @safe
    @lead_only
    def delete_lesson(self, lid: str) -> dict:
        self._store.delete_lesson(lid)
        return {"lessons": self._store.lessons()}

    @safe
    def history(self) -> dict:
        if self._role() == "member":
            return {"runs": [{"run_id": r["name"], "as_of": None, "logic_version": None, "alert_count": None,
                              "feedback_count": None} for r in self.list_reports().get("reports", [])[:30]],
                    "logic_versions": []}
        active = self._store.active_logic()
        return {"runs": self._store.list_runs(),
                "logic_versions": [{"version": v, "name": p.name, "active": p == active}
                                   for v, p in self._store.logic_versions()]}

    @safe
    @lead_only
    def set_active_logic(self, version: int) -> dict:
        self._store.set_active_logic(int(version))
        return self.history()

    # ------------------------------------------------------------- style & settings
    @safe
    def get_style(self) -> dict:
        return self._store.get_style()

    @safe
    @lead_only
    def save_style(self, d: dict) -> dict:
        self._store.save_style(d)
        return self._store.get_style()

    @safe
    @lead_only
    def add_style_sample(self, text: str) -> dict:
        self._store.add_style_sample(text)
        return self._store.get_style()

    @safe
    @lead_only
    def preview_style(self) -> dict:
        run = self._latest()
        d = max(run["result"]["digest"], key=lambda x: x["camp_high"] + x["pl_high"])
        rows = pic_rows(run["result"], d["pic"])
        out = self._ask(style_prompt(self._store.get_style(), d, {"pl": rows["pl"][:5], "camp": rows["camp"][:8]}), STYLE_SCHEMA)
        return {"slack": out["slack"], "pic": d["pic"]}

    @safe
    @lead_only
    def save_pic_address(self, pic: str, d: dict) -> dict:
        self._store.set_pic_address(pic, d)
        return self._store.get_style()

    @safe
    @lead_only
    def rewrite_message(self, pic: str, run_id: str | None = None) -> dict:
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        d = next((x for x in run["result"]["digest"] if x["pic"] == pic), None)
        if d is None:
            raise ValueError(f"Không có PIC {pic} trong lần chạy này")
        rows = pic_rows(run["result"], pic)
        out = self._ask(style_prompt(self._store.get_style(), d, {"pl": rows["pl"], "camp": rows["camp"]}), STYLE_SCHEMA)
        context = {"time_gone": Windows(date.fromisoformat(run["result"]["as_of"])).time_gone}
        if not grounded(out["slack"], list(rows["all"].values()) + [d, context]):
            raise ValueError("Claude viết số không khớp dữ liệu – đã giữ tin nhắn cũ, thử lại nhé")
        ai = run.get("ai") or {"claude_ok": True, "error": None, "review": [], "per_pic": {}}
        ai["per_pic"].setdefault(pic, {"insights": [], "todos": [], "dropped": 0})["slack"] = out["slack"]
        self._store.update_run_ai(run["run_id"], ai)
        return {"slack": out["slack"], "pic": pic}

    @safe
    def memory_info(self) -> dict:
        return self._store.usage()

    @safe
    @lead_only
    def prune_memory(self) -> dict:
        deleted = self._store.prune()
        return {"deleted": deleted, **self._store.usage()}

    @safe
    def get_settings(self) -> dict:
        return self._store.get_settings()

    @safe
    def save_settings(self, d: dict) -> dict:
        if self._role() == "member" and set(d) - MEMBER_SETTINGS:
            raise PermissionError(LEAD_ONLY)
        self._store.save_settings(d)
        return self._store.get_settings()

    @safe
    def email_map_suggestions(self) -> dict:
        saved = self._store.get_settings().get("email_map", {})
        users = sorted({u for u in self._ensure_inputs().activity["user"].dropna().astype(str).str.strip().str.lower() if u})
        pics = sorted({d["pic"] for d in self._latest()["result"]["digest"]})
        suggested = suggest_email_map(users, pics)
        return {"email_map": {u: saved.get(u) or suggested.get(u, "") for u in users}, "pics": pics}

    # ------------------------------------------------------------- update & export
    @safe
    def check_update(self) -> dict:
        repo = self._repo()
        rel = self._release(repo)
        return {"current": __version__, "repo": repo, "latest": rel.tag if rel else None,
                "newer": bool(rel and is_newer(rel.tag, __version__)), "notes": rel.notes if rel else "",
                "published": rel.published if rel else "",
                "previous": [{"tag": r.tag, "notes": r.notes, "published": r.published} for r in self._recent(repo)][1:]
                if rel else []}

    @safe
    def whats_new(self) -> dict:
        """Notes for the installed version from the bundled CHANGELOG.md; `show` once after each update."""
        sections = parse_changelog(bundled_text())
        cur = __version__.split("-")[0]
        mine = sections.get(cur, {"date": "", "notes": ""})
        seen = self._store.get_settings().get("last_seen_version")
        return {"version": cur, "date": mine["date"], "notes": mine["notes"],
                "show": "-dev" not in __version__ and seen != __version__ and bool(mine["notes"]),
                "previous": [{"tag": f"v{v}", "notes": s["notes"], "published": s["date"]}
                             for v, s in sections.items() if v != cur][:5]}

    @safe
    def mark_whats_new_seen(self) -> dict:
        self._store.save_settings({"last_seen_version": __version__})
        return {"ok": True}

    @safe
    def install_update(self) -> dict:
        rel = self._release(self._repo())
        if not rel or not is_newer(rel.tag, __version__):
            raise ValueError("Không có bản cập nhật mới")
        exe = download_verified(rel, self._store.base / "updates")
        apply_update(exe)
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}

    @safe
    @lead_only
    def export(self, pic: str, path: str | None = None, run_id: str | None = None) -> dict:
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        if path is None:
            import webview
            picked = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"PMKT Alert - {pic}.xlsx")
            if not picked:
                return {"cancelled": True}
            path = picked if isinstance(picked, str) else picked[0]
        return {"path": str(export_pic(run["result"], run.get("ai"), pic, Path(path))), "run_id": run["run_id"]}

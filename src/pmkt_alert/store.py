"""User state under %APPDATA%\\PMKT Alert: runs, feedback, lessons, style, settings, logic versions.
Plain JSON written atomically; a corrupt file is set aside and defaults are used."""
import json
import os
import shutil
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .logic import version_from_name

DEFAULT_STYLE = {"language": "vi_en_terms", "pronoun": "em_anhchi", "length": "short", "tone": "friendly_direct",
                 "emoji": "low", "samples": [], "rules": "", "pic_address": {}}
DEFAULT_SETTINGS = {"auto_update_check": True, "email_map": {}, "last_inputs": {}, "active_logic": None,
                    "github_repo": "", "ads_account": ""}


def default_base() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "PMKT Alert"
    return Path.home() / ".pmkt-alert"


def _locked(fn):
    def wrapper(self, *a, **k):
        with self._lock:
            return fn(self, *a, **k)
    return wrapper


def _id() -> str:
    return uuid.uuid4().hex[:8]


class Store:
    # pywebview runs each JS call on its own thread; all read-modify-write goes through this lock.
    _lock = threading.RLock()

    def __init__(self, base: Path):
        self.base = Path(base)
        for d in ("runs", "logic"):
            (self.base / d).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- json io
    def _read(self, name: str, default):
        with self._lock:
            return self._read_unlocked(name, default)

    def _read_unlocked(self, name: str, default):
        p = self.base / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            p.rename(p.with_name(f"{p.name}.corrupt-{datetime.now():%Y%m%d%H%M%S}"))
            return default

    def _write(self, name: str, data) -> None:
        p = self.base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex[:6]}.tmp")
        with self._lock:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)

    # ------------------------------------------------------------- runs
    def save_run(self, result_json: dict, ai_json: dict | None) -> str:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        while (self.base / "runs" / f"{run_id}.json").exists():
            run_id += "b"
        self._write(f"runs/{run_id}.json", {"run_id": run_id, "result": result_json, "ai": ai_json})
        return run_id

    def load_run(self, run_id: str) -> dict:
        return self._read(f"runs/{run_id}.json", {})

    @_locked
    def update_run_ai(self, run_id: str, ai_json: dict) -> None:
        run = self.load_run(run_id)
        run["ai"] = ai_json
        self._write(f"runs/{run_id}.json", run)

    def list_runs(self) -> list[dict]:
        fb = self.list_feedback()
        out = []
        for p in sorted((self.base / "runs").glob("*.json"), reverse=True):
            run = self._read(f"runs/{p.name}", {})
            res = run.get("result") or {}
            alerts = sum(r.get("pacing_sev") in ("HIGH", "MED") for r in res.get("pl", [])) + \
                sum(r.get("sev") in ("HIGH", "MED") for r in res.get("camp", []))
            out.append({"run_id": run.get("run_id", p.stem), "as_of": res.get("as_of"),
                        "logic_version": res.get("logic_version"), "alert_count": alerts,
                        "feedback_count": sum(f.get("run_id") == run.get("run_id") for f in fb)})
        return out

    # ------------------------------------------------------------- feedback / lessons
    @_locked
    def add_feedback(self, item: dict) -> str:
        items = self._read("feedback.json", [])
        fid = _id()
        items.append({"status": "new", "created": datetime.now().isoformat(timespec="seconds"), **item, "id": fid})
        self._write("feedback.json", items)
        return fid

    def list_feedback(self, status: str | None = None) -> list[dict]:
        return [f for f in self._read("feedback.json", []) if status is None or f.get("status") == status]

    @_locked
    def set_feedback_status(self, fid: str, status: str) -> None:
        items = self._read("feedback.json", [])
        for f in items:
            if f["id"] == fid:
                f["status"] = status
        self._write("feedback.json", items)

    def lessons(self) -> list[dict]:
        return self._read("lessons.json", [])

    @_locked
    def add_lesson(self, text: str, source: str) -> str:
        items = self.lessons()
        lid = _id()
        items.append({"id": lid, "text": text, "source": source, "created": datetime.now().isoformat(timespec="seconds")})
        self._write("lessons.json", items)
        return lid

    @_locked
    def delete_lesson(self, lid: str) -> None:
        self._write("lessons.json", [x for x in self.lessons() if x["id"] != lid])

    # ------------------------------------------------------------- style / settings
    def get_style(self) -> dict:
        return {**DEFAULT_STYLE, **self._read("style.json", {})}

    def save_style(self, d: dict) -> None:
        with self._lock:
            self._write("style.json", {**self.get_style(), **d})

    @_locked
    def set_pic_address(self, pic: str, d: dict) -> None:
        style = self.get_style()
        style["pic_address"] = {**style.get("pic_address", {}), pic: {k: str(d.get(k, "")).strip() for k in ("self", "call", "name")}}
        self.save_style(style)

    @_locked
    def add_style_sample(self, text: str) -> None:
        style = self.get_style()
        style["samples"] = [*style["samples"], text][-10:]
        self.save_style(style)

    def get_settings(self) -> dict:
        return {**DEFAULT_SETTINGS, **self._read("settings.json", {})}

    def save_settings(self, d: dict) -> None:
        with self._lock:
            self._write("settings.json", {**self.get_settings(), **d})

    # ------------------------------------------------------------- logic versions
    def import_logic(self, path: Path) -> Path:
        dest = self.base / "logic" / Path(path).name
        if Path(path).resolve() != dest.resolve():
            shutil.copyfile(path, dest)
        self.save_settings({"active_logic": dest.name})
        return dest

    def logic_versions(self) -> list[tuple[int, Path]]:
        return sorted((version_from_name(p.name), p) for p in (self.base / "logic").glob("*.xlsx"))

    def active_logic(self) -> Path | None:
        name = self.get_settings().get("active_logic")
        if name and (self.base / "logic" / name).exists():
            return self.base / "logic" / name
        versions = self.logic_versions()
        return versions[-1][1] if versions else None

    def set_active_logic(self, version: int) -> None:
        for v, p in self.logic_versions():
            if v == version:
                self.save_settings({"active_logic": p.name})
                return
        raise ValueError(f"Không có Alert_Logic Ver {version}")

    # ------------------------------------------------------------- proposals
    def proposals(self) -> list[dict]:
        return self._read("proposals.json", [])

    @_locked
    def save_proposals(self, items: list[dict]) -> None:
        self._write("proposals.json", items)

    @_locked
    def set_proposal_status(self, pid: str, status: str) -> None:
        items = self.proposals()
        for x in items:
            if x["id"] == pid:
                x["status"] = status
        self.save_proposals(items)

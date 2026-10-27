"""Everything the UI can call (exposed to JavaScript via pywebview's js_api).
Every public method returns JSON-serializable data and never raises."""
import functools
import json
import traceback
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .ai import generate, offline, pic_rows
from .aggregate import asin_map
from .backtest import apply_approved, propose_from_feedback, proposals_from_review
from .claude import ClaudeError, ask, check_status, grounded, open_login
from .claude import _exe as claude_exe
from .claude import install as install_claude_cli
from .evidence import evidence
from .export import export_pic
from .loaders import ROLES, InputError, detect_inputs, load_inputs, role_of
from .logic import LogicError, load_logic, version_from_name
from .pipeline import result_to_json, run_rules
from .prompts import STYLE_SCHEMA, TEAM_SCHEMA, style_prompt, team_prompt
from .scorecard import METRICS, scorecard, weekly
from .rules.actions import suggest_email_map
from .store import Store
from .updater import DEFAULT_REPO, apply_update, download_verified, is_newer, latest_release, recent_releases
from .windows import Windows


def safe(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except (InputError, LogicError, ClaudeError, ValueError, RuntimeError) as e:
            return {"error": str(e)}
        except Exception as e:  # never let a traceback reach the UI
            self._log(traceback.format_exc())
            return {"error": f"Lỗi không mong đợi: {e} (chi tiết: {self._store.base / 'error.log'})"}
    return wrapper


class Api:
    def __init__(self, store: Store, ask_fn=ask, status_fn=check_status, release_fn=latest_release,
                 recent_fn=recent_releases):
        self._store, self._status = store, status_fn
        self._ask = self._with_note(ask_fn)
        self._release, self._recent = release_fn, recent_fn
        self._window = None
        self._inputs = None
        self._paths: list[str] = []

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

    def _progress(self, step: str, state: str, detail: str = "") -> None:
        if self._window is not None:
            self._window.evaluate_js(f"window.onProgress && onProgress({json.dumps(step)}, {json.dumps(state)}, {json.dumps(detail)})")

    def _latest(self) -> dict:
        runs = self._store.list_runs()
        if not runs:
            raise ValueError("Chưa có lần chạy nào")
        return self._store.load_run(runs[0]["run_id"])

    def _logic(self):
        active = self._store.active_logic()
        if not active:
            raise ValueError("Chưa có file Alert_Logic")
        return load_logic(active)

    def _ensure_inputs(self):
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
                                                 file_types=("Excel (*.xlsx;*.xlsm)",))
        return {"paths": list(picked) if picked else []}

    def _on_drop(self, event: dict) -> None:
        """Native drop handler (registered in app.py): only Python sees the dropped files' full paths."""
        files = (event.get("dataTransfer") or {}).get("files", [])
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths and self._window is not None:
            self._window.evaluate_js(f"window.onDropPaths && onDropPaths({json.dumps(paths)})")

    @safe
    def detect(self, paths: list[str]) -> dict:
        """Classify picked files/folders. Earlier paths win per role, so the UI sends new picks first;
        inside a folder the newest file wins. Partial picks are fine: missing roles are listed."""
        files: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                files += sorted((f for f in p.glob("*.xlsx") if not f.name.startswith("~$")),
                                key=lambda f: f.stat().st_mtime, reverse=True)
            elif p.exists():
                files.append(p)
        roles, unknown = {}, []
        for f in files:
            try:
                role = role_of(f)
            except Exception:
                role = None
            if role is None:
                unknown.append(f.name)
            elif role not in roles:
                roles[role] = {"path": str(f), "name": f.name, "size_mb": round(f.stat().st_size / 1e6, 1)}
        return {"roles": roles, "missing": [r for r in ROLES if r not in roles], "unknown": unknown}

    @safe
    def run(self, paths: list[str], as_of: str | None = None, use_claude: bool = True) -> dict:
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
            load_logic(picked)  # validate before importing: a broken file must not become active
            self._store.import_logic(picked)
        logic = self._logic()
        self._progress("load", "done", f"{len(inputs.raw):,} dòng raw · {len(inputs.ads):,} dòng ads_camp")

        self._progress("rules", "running", "Tầng 0–4")
        result = run_rules(inputs, logic, date.fromisoformat(as_of) if as_of else None)
        rj = result_to_json(result)
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
            self._store.update_run_ai(run_id, ai)
            self._progress("claude", "warn", ai["error"])
        elif use_claude:
            careful = bool(self._store.get_settings().get("careful_mode", True))
            self._progress("claude", "running", "5 bước/PIC: dữ kiện → nháp → kiểm tra → biên tập → kiểm tra lại"
                           if careful else "Chế độ nhanh: nháp → kiểm tra")
            amap = asin_map(inputs.products, result.as_of)
            l7d = Windows(result.as_of).l7d
            inel = inputs.ineligible[(inputs.ineligible["date"] >= l7d[0]) & (inputs.ineligible["date"] <= l7d[1])]
            inel = inel.merge(amap, on="asin")[["asin", "pl", "pic", "reason"]].drop_duplicates("asin")
            ai = generate(rj, logic, self._store, inputs.event_days, inputs.defind_text,
                          inel.to_dict("records"), ask_fn=self._ask, careful=careful)
            self._store.update_run_ai(run_id, ai)
            try:
                proposals_from_review(ai["review"], logic, self._store, inputs, result.as_of)
            except Exception:  # a failed backtest must not hide the run
                self._log(traceback.format_exc())
            self._progress("claude", "done" if ai["claude_ok"] else "warn", ai["error"] or "")
        return {"run_id": run_id, "result": rj, "ai": ai}

    @safe
    def evidence(self, unit_id: str, run_id: str | None = None) -> dict:
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        rj = run["result"]
        logic_path = next((p for v, p in self._store.logic_versions() if v == rj["logic_version"]), None) \
            or self._store.active_logic()
        ev = evidence(self._ensure_inputs(), load_logic(logic_path), rj, unit_id)
        return {**ev, "files": rj.get("inputs", {}).get("files", {}), "logic_file": Path(logic_path).name,
                "as_of": rj["as_of"]}

    def _run_or_latest(self, run_id: str | None) -> dict:
        run = self._store.load_run(run_id) if run_id else self._latest()
        if not run:
            raise ValueError("Không tìm thấy lần chạy")
        return run

    def _runs_history(self) -> list[dict]:
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
        return {"run_id": run["run_id"], "scorecard": scorecard(run["result"], weights),
                "weekly": weekly(self._ensure_inputs(), date.fromisoformat(run["result"]["as_of"])),
                "runs": self._runs_history(), "team_review": run.get("team_review")}

    @safe
    def save_score_weights(self, weights: dict) -> dict:
        keys = {m["key"] for m in METRICS}
        clean = {k: max(0.0, float(v)) for k, v in weights.items() if k in keys}
        self._store.save_settings({"score_weights": clean})
        return {"weights": clean}

    @safe
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
        runs = self._store.list_runs()
        run = self._store.load_run(runs[0]["run_id"]) if runs else {}
        return {"findings": ((run.get("ai") or {}).get("review") or []), "proposals": self._store.proposals(),
                "feedback": self._store.list_feedback()}

    @safe
    def set_proposal(self, pid: str, status: str) -> dict:
        if status not in ("approved", "rejected", "pending"):
            raise ValueError("Trạng thái không hợp lệ")
        self._store.set_proposal_status(pid, status)
        return {"proposals": self._store.proposals()}

    @safe
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
    def delete_lesson(self, lid: str) -> dict:
        self._store.delete_lesson(lid)
        return {"lessons": self._store.lessons()}

    @safe
    def history(self) -> dict:
        active = self._store.active_logic()
        return {"runs": self._store.list_runs(),
                "logic_versions": [{"version": v, "name": p.name, "active": p == active}
                                   for v, p in self._store.logic_versions()]}

    @safe
    def set_active_logic(self, version: int) -> dict:
        self._store.set_active_logic(int(version))
        return self.history()

    # ------------------------------------------------------------- style & settings
    @safe
    def get_style(self) -> dict:
        return self._store.get_style()

    @safe
    def save_style(self, d: dict) -> dict:
        self._store.save_style(d)
        return self._store.get_style()

    @safe
    def add_style_sample(self, text: str) -> dict:
        self._store.add_style_sample(text)
        return self._store.get_style()

    @safe
    def preview_style(self) -> dict:
        run = self._latest()
        d = max(run["result"]["digest"], key=lambda x: x["camp_high"] + x["pl_high"])
        rows = pic_rows(run["result"], d["pic"])
        out = self._ask(style_prompt(self._store.get_style(), d, {"pl": rows["pl"][:5], "camp": rows["camp"][:8]}), STYLE_SCHEMA)
        return {"slack": out["slack"], "pic": d["pic"]}

    @safe
    def save_pic_address(self, pic: str, d: dict) -> dict:
        self._store.set_pic_address(pic, d)
        return self._store.get_style()

    @safe
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
    def prune_memory(self) -> dict:
        deleted = self._store.prune()
        return {"deleted": deleted, **self._store.usage()}

    @safe
    def get_settings(self) -> dict:
        return self._store.get_settings()

    @safe
    def save_settings(self, d: dict) -> dict:
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

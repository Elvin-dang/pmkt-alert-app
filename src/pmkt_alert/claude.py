"""Claude Code (local CLI) client: status check, JSON calls, and the grounding check that
drops any sentence quoting a number the rules did not produce."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass

import jsonschema

ISOLATED = ["--output-format", "json", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
            "--setting-sources", "", "--system-prompt", "Bạn là trợ lý phân tích dữ liệu. Chỉ trả lời đúng yêu cầu."]
_AUTH = re.compile(r"login|log in|auth|api key|credential", re.IGNORECASE)


class ClaudeError(Exception):
    """retryable=True only for malformed output; timeouts, auth and missing CLI are fatal."""

    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


@dataclass
class ClaudeStatus:
    installed: bool
    version: str | None
    logged_in: bool
    responds: bool
    latency_s: float | None
    error: str | None

    @property
    def level(self) -> str:
        if not self.installed or not self.logged_in:
            return "bad"
        return "ok" if self.responds else "warn"

    def to_dict(self) -> dict:
        return {**asdict(self), "level": self.level}


def _exe() -> str | None:
    # npm installs claude.cmd on Windows; which() honours PATHEXT, a bare "claude" would not.
    return shutil.which("claude")


def _run(runner, args: list[str], stdin: str | None, timeout: int):
    kw = dict(input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
              cwd=tempfile.gettempdir())
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return runner(args, **kw)


def check_status(runner=subprocess.run) -> ClaudeStatus:
    exe = _exe()
    if not exe:
        return ClaudeStatus(False, None, False, False, None, "Chưa cài Claude Code (không tìm thấy lệnh claude)")
    try:
        v = _run(runner, [exe, "--version"], None, 15)
    except (FileNotFoundError, OSError):
        return ClaudeStatus(False, None, False, False, None, "Chưa cài Claude Code (không tìm thấy lệnh claude)")
    except subprocess.TimeoutExpired:
        return ClaudeStatus(True, None, True, False, None, "claude --version không phản hồi")
    version = (v.stdout or "").strip().splitlines()[0] if (v.stdout or "").strip() else None
    t0 = time.monotonic()
    try:
        p = _run(runner, [exe, "-p", *ISOLATED], "Trả lời đúng một chữ: OK", 45)
    except subprocess.TimeoutExpired:
        return ClaudeStatus(True, version, True, False, None, "Claude Code phản hồi quá chậm (>45s)")
    latency = round(time.monotonic() - t0, 1)
    text = (p.stdout or "") + (p.stderr or "")
    try:
        outer = json.loads(p.stdout)
    except (json.JSONDecodeError, TypeError):
        outer = {"is_error": True, "result": text}
    if outer.get("is_error") or p.returncode != 0:
        msg = str(outer.get("result") or text)[:200]
        if _AUTH.search(msg):
            return ClaudeStatus(True, version, False, False, None, "Chưa đăng nhập Claude Code")
        return ClaudeStatus(True, version, True, False, None, msg or "Claude Code báo lỗi")
    return ClaudeStatus(True, version, True, True, latency, None)


def _first_object(text: str) -> dict:
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    raise ClaudeError("Claude không trả về JSON", retryable=True)


def ask(prompt: str, schema: dict, runner=subprocess.run, timeout: int = 240) -> dict:
    exe = _exe()
    if not exe:
        raise ClaudeError("Chưa cài Claude Code")
    try:
        p = _run(runner, [exe, "-p", *ISOLATED], prompt, timeout)
    except (FileNotFoundError, OSError):
        raise ClaudeError("Chưa cài Claude Code")
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"Claude Code quá thời gian ({timeout}s)")
    try:
        outer = json.loads(p.stdout)
    except (json.JSONDecodeError, TypeError):
        raise ClaudeError("Claude Code báo lỗi: " + ((p.stderr or p.stdout or "").strip()[:200] or f"mã {p.returncode}"))
    if outer.get("is_error") or p.returncode != 0:
        raise ClaudeError("Claude Code báo lỗi: " + str(outer.get("result", ""))[:200])
    obj = _first_object(str(outer.get("result", "")))
    try:
        jsonschema.validate(obj, schema)
    except jsonschema.ValidationError as e:
        raise ClaudeError(f"Kết quả Claude sai cấu trúc: {e.message[:120]}", retryable=True)
    return obj


# ----------------------------------------------------------------- grounding
_DATES = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b(?:ngày|T|tháng|tuần)\s?\d{1,2}\b", re.IGNORECASE)
_TOKEN = re.compile(r"(\$)?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(k\b|%)?", re.IGNORECASE)


def numbers_in(text: str) -> list[tuple[float, bool, int]]:
    """(value, is_percent, precision exponent). Dates, month refs and bare integers ≤ 10 are ignored."""
    out, clean = [], _DATES.sub(" ", text)
    for m in _TOKEN.finditer(clean):
        dollar, whole, frac, suffix = m.groups()
        if m.start() > 0 and clean[m.start() - 1].isalpha():
            continue  # part of a word like "x2", "T10", "L7D"
        value = float(whole.replace(",", "") + ("." + frac if frac else ""))
        decimals = len(frac) if frac else 0
        suffix = (suffix or "").lower()
        if suffix == "k":
            value, decimals = value * 1000, decimals - 3
        if not dollar and not suffix and not frac and value <= 10:
            continue
        out.append((value, suffix == "%", decimals))
    return out


def _values(rows: list[dict]) -> list[float]:
    return [abs(float(v)) for r in rows for v in r.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v]


def grounded(text: str, rows: list[dict]) -> bool:
    vals = _values(rows)
    for value, is_pct, dec in numbers_in(text):
        tol = 0.5 * 10 ** (-dec) + 1e-9
        cands = [v * 100 for v in vals] if is_pct else vals
        if not any(abs(value - c) <= tol for c in cands):
            return False
    return True


def filter_grounded(items: list[dict], rows_by_id: dict[str, dict], text_keys: tuple[str, ...],
                    implicit: list[dict] = ()) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for it in items:
        refs = it.get("refs", [])
        if any(r not in rows_by_id for r in refs):
            dropped.append(it)
            continue
        rows = [rows_by_id[r] for r in refs] + list(implicit)
        (kept if all(grounded(str(it.get(k, "")), rows) for k in text_keys) else dropped).append(it)
    return kept, dropped

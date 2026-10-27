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
from pathlib import Path

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
        # "error" is reserved for failed Api calls in the UI, so the reason travels as "detail".
        d = asdict(self)
        d["detail"] = d.pop("error")
        return {**d, "level": self.level}


def _exe() -> str | None:
    # npm installs claude.cmd on Windows; which() honours PATHEXT, a bare "claude" would not.
    # Right after an in-app install the native installer's bin dir is not on this process's PATH yet.
    found = shutil.which("claude")
    if found:
        return found
    name = "claude.exe" if sys.platform == "win32" else "claude"
    native = Path.home() / ".local" / "bin" / name
    return str(native) if native.exists() else None


def install_command() -> list[str]:
    """Official native installers (code.claude.com/docs/en/setup); no admin rights needed."""
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "irm https://claude.ai/install.ps1 | iex"]
    return ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]


def install(runner=subprocess.run) -> dict:
    try:
        p = _run(runner, install_command(), None, 600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "output": f"Cài đặt không chạy được: {e}"}
    output = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()[-2000:]
    return {"ok": p.returncode == 0 and _exe() is not None, "output": output}


def login_command(exe: str) -> list[str]:
    """Open a terminal running `claude`, where the user logs in through the browser."""
    if sys.platform == "win32":
        return ["cmd", "/c", "start", "Claude Code", "cmd", "/k", exe]
    if sys.platform == "darwin":
        return ["osascript", "-e", f'tell application "Terminal" to do script "\\"{exe}\\""',
                "-e", 'tell application "Terminal" to activate']
    return ["x-terminal-emulator", "-e", exe]


def open_login(exe: str) -> None:
    subprocess.Popen(login_command(exe), close_fds=True)


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
_DATES = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|\b(?:ngày|T|tháng|tuần)\s?\d{1,2}\b",
                    re.IGNORECASE)
_TOKEN = re.compile(r"(\$)?\s?(\d+(?:[.,]\d+)*)\s?(k\b|%)?", re.IGNORECASE)


def _readings(raw: str) -> list[tuple[float, int]]:
    """Possible (value, decimals) for a number written either way: 1,234.5 (EN) or 1.234,5 (VI).
    "187.268" / "527,640" are ambiguous (thousands or decimals) – both readings are kept."""
    if "." in raw and "," in raw:
        dec = "." if raw.rfind(".") > raw.rfind(",") else ","
        whole, frac = raw.rsplit(dec, 1)
        return [(float(whole.replace(".", "").replace(",", "") + "." + frac), len(frac))]
    sep = "." if "." in raw else "," if "," in raw else None
    if sep is None:
        return [(float(raw), 0)]
    parts = raw.split(sep)
    out = []
    if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
        out.append((float("".join(parts)), 0))  # thousands separators
    if len(parts) == 2:
        out.append((float(parts[0] + "." + parts[1]), len(parts[1])))  # decimal separator
    return out


def number_tokens(text: str) -> list[list[tuple[float, bool, int]]]:
    """Each quoted number with its possible readings (value, is_percent, precision exponent).
    Dates, month refs, words like x2/L7D and bare integers ≤ 10 are ignored."""
    out, clean = [], _DATES.sub(" ", text)
    for m in _TOKEN.finditer(clean):
        dollar, raw, suffix = m.groups()
        first = m.start(1) if dollar else m.start(2)  # the match may begin with a space
        if first > 0 and clean[first - 1].isalpha():
            continue
        suffix = (suffix or "").lower()
        readings = []
        for value, decimals in _readings(raw):
            if suffix == "k":
                value, decimals = value * 1000, decimals - 3
            readings.append((value, suffix == "%", decimals))
        if not dollar and not suffix and len(readings) == 1 and readings[0][2] == 0 and readings[0][0] <= 10:
            continue
        out.append(readings)
    return out


def numbers_in(text: str) -> list[tuple[float, bool, int]]:
    return [r[0] for r in number_tokens(text)]


def _values(rows: list[dict]) -> list[float]:
    out = []
    for r in rows:
        for v in r.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                out.append(abs(float(v)))
            elif isinstance(v, str) and v.isdigit():  # e.g. campaign_id kept as text
                out.append(float(v))
    return out


def grounded(text: str, rows: list[dict]) -> bool:
    vals = _values(rows)

    def matches(value, is_pct, dec):
        tol = 0.5 * 10 ** (-dec) + 1e-9
        return any(abs(value - (c * 100 if is_pct else c)) <= tol for c in vals)
    return all(any(matches(*r) for r in readings) for readings in number_tokens(text))


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

"""Version check and self-update from public GitHub Releases."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_REPO = "Elvin-dang/pmkt-alert-app"


@dataclass
class Release:
    tag: str
    notes: str
    published: str
    exe_url: str
    sha_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_version(tag: str) -> tuple[int, int, int]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", str(tag).strip())
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def is_newer(tag: str, current: str) -> bool:
    return parse_version(tag) > parse_version(current)


def _get(url: str, fetch, timeout: int = 10):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "pmkt-alert"})
    with fetch(req, timeout=timeout) as r:
        return r.read()


def _release(d: dict) -> Release | None:
    assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
    exe = next((u for n, u in assets.items() if n.lower().endswith(".exe")), None)
    sha = next((u for n, u in assets.items() if n.lower().endswith(".sha256")), None)
    if not exe or not sha:
        return None
    return Release(d.get("tag_name", ""), d.get("body") or "", d.get("published_at") or "", exe, sha)


def latest_release(repo: str, fetch=urllib.request.urlopen) -> Release | None:
    if not repo:
        return None
    try:
        return _release(json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest", fetch)))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def recent_releases(repo: str, fetch=urllib.request.urlopen, n: int = 5) -> list[Release]:
    if not repo:
        return []
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{repo}/releases?per_page={n}", fetch))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return [r for r in map(_release, data) if r]


def download_verified(rel: Release, dest_dir: Path, fetch=urllib.request.urlopen) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    expected = _get(rel.sha_url, fetch, 30).decode("utf-8", "replace").split()[0].lower()
    name = rel.exe_url.rsplit("/", 1)[-1]
    part = dest_dir / f"{name}.part"
    h = hashlib.sha256()
    req = urllib.request.Request(rel.exe_url, headers={"User-Agent": "pmkt-alert"})
    with fetch(req, timeout=300) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise ValueError("Checksum không khớp – bản tải về bị lỗi, đã xoá")
    final = dest_dir / name
    os.replace(part, final)
    return final


def swap_script(new_exe: Path, current_exe: Path, pid: int) -> str:
    """Batch file (UTF-8, chcp 65001 for non-ASCII profile paths). Waits for the app to exit, retries the
    move while the exe is still locked, and always relaunches – the old exe if the swap fails."""
    pause = "ping -n 2 127.0.0.1 >nul"  # `timeout` fails without a console
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        ":wait",
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul',
        f"if not errorlevel 1 ({pause} & goto wait)",
        "set /a tries=0",
        ":move",
        f'move /y "{new_exe}" "{current_exe}" >nul',
        "if not errorlevel 1 goto ok",
        "set /a tries+=1",
        "if %tries% geq 30 goto fail",
        pause,
        "goto move",
        ":ok",
        f'start "" "{current_exe}"',
        'del "%~f0"',
        "exit /b 0",
        ":fail",
        f'start "" "{current_exe}"',
        'del "%~f0"',
        "exit /b 1",
    ])


def apply_update(new_exe: Path) -> None:
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        raise RuntimeError("Chỉ cập nhật được bản .exe trên Windows")
    script = Path(tempfile.gettempdir()) / "pmkt-alert-update.bat"
    # One-file builds run as a child of the bootloader, which holds the exe until it exits: wait for the parent.
    pid = os.getppid() if hasattr(sys, "_MEIPASS") else os.getpid()
    script.write_text(swap_script(Path(new_exe), Path(sys.executable), pid), encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)

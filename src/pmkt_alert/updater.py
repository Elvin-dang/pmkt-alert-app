"""Version check and self-update from public GitHub Releases."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
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


EXE_NAME = "PMKT-Alert.exe"


def _wait_pid(pid: int, timeout: float) -> None:
    """Block until process `pid` has exited (or timeout)."""
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if handle:
            k32.WaitForSingleObject(handle, int(timeout * 1000))
            k32.CloseHandle(handle)
        return
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)


def _launch(path: Path, *args: str) -> None:
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
    subprocess.Popen([str(path), *args], close_fds=True, creationflags=flags)


def finish_update(old_exe: Path, pid: int, me: Path, wait_fn=_wait_pid, copy_fn=shutil.copy2, launch_fn=_launch,
                  unlink_fn=lambda p: Path(p).unlink(), sleep_fn=time.sleep, tries: int = 30, log=print) -> Path:
    """Run by the NEW exe (`--finish-update <old_exe> <pid>`): no console, no batch file.
    Waits for the old app to exit, copies itself to <old folder>/PMKT-Alert.exe (retrying while Windows
    still locks it), removes an old versioned file, starts the app. On failure the old app is reopened."""
    old_exe = Path(old_exe)
    target = old_exe.with_name(EXE_NAME)
    log(f"finish-update: wait for pid {pid}")
    wait_fn(pid, 60)
    for attempt in range(1, tries + 1):
        try:
            copy_fn(me, target)
            log(f"finish-update: copied to {target} (attempt {attempt})")
            break
        except OSError as e:
            log(f"finish-update: copy attempt {attempt} failed: {e}")
            sleep_fn(1)
    else:
        log("finish-update: giving up, reopening the old app")
        launch_fn(old_exe)
        return old_exe
    if old_exe.name.lower() != EXE_NAME.lower():
        try:
            unlink_fn(old_exe)
        except OSError as e:
            log(f"finish-update: could not remove {old_exe}: {e}")
    launch_fn(target)
    log(f"finish-update: started {target}")
    return target


def apply_update(new_exe: Path) -> None:
    """Called by the OLD app after download: start the new exe to finish the swap, then the caller exits."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        raise RuntimeError("Chỉ cập nhật được bản .exe trên Windows")
    # One-file builds run as a child of the bootloader, which holds the exe until it exits: wait for the parent.
    pid = os.getppid() if hasattr(sys, "_MEIPASS") else os.getpid()
    _launch(Path(new_exe), "--finish-update", sys.executable, str(pid))


def cleanup_downloads(updates_dir: Path) -> None:
    """Remove downloaded installers left from a previous update (best effort)."""
    running = Path(sys.executable).resolve()
    for p in Path(updates_dir).glob("*.exe"):
        try:
            if p.resolve() != running:
                p.unlink()
        except OSError:
            pass

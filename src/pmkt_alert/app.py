"""Desktop entry point: a native window (Edge WebView2 on Windows) showing ui/index.html."""
import sys
from pathlib import Path


def ui_path() -> Path:
    # One-file builds unpack data to sys._MEIPASS/pmkt_alert/ui (see pmkt_alert.spec).
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "pmkt_alert" / "ui" / "index.html"
    return Path(__file__).parent / "ui" / "index.html"


def file_type_entries(exe: str) -> list[tuple[str, str, str]]:
    """Per-user registry entries (HKCU, no admin) so double-clicking a .pmkt opens this app."""
    return [(r"Software\Classes\.pmkt", "", "PMKTAlert.Run"),
            (r"Software\Classes\PMKTAlert.Run", "", "PMKT Alert run"),
            (r"Software\Classes\PMKTAlert.Run\DefaultIcon", "", f'"{exe}",0'),
            (r"Software\Classes\PMKTAlert.Run\shell\open\command", "", f'"{exe}" "%1"')]


def register_file_type() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import winreg
    for key, name, value in file_type_entries(sys.executable):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def main() -> None:
    if "--selfcheck" in sys.argv:  # used by CI on the built exe
        sys.exit(0 if ui_path().exists() else 1)
    if "--finish-update" in sys.argv:  # started by the old app after it downloaded this exe
        from datetime import datetime

        from pmkt_alert.store import default_base
        from pmkt_alert.updater import finish_update
        i = sys.argv.index("--finish-update")
        log_path = default_base() / "update.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def log(msg: str) -> None:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
        finish_update(Path(sys.argv[i + 1]), int(sys.argv[i + 2]), me=Path(sys.executable), log=log)
        return
    import webview
    from webview.dom import DOMEventHandler

    from pmkt_alert.api import Api
    from pmkt_alert.store import Store, default_base

    from pmkt_alert.updater import cleanup_downloads
    store = Store(default_base())
    cleanup_downloads(store.base / "updates")
    api = Api(store)
    api._startup_file = next((a for a in sys.argv[1:] if a.lower().endswith(".pmkt")), None)
    try:
        register_file_type()
    except OSError:
        pass
    window = webview.create_window("PMKT Alert", url=str(ui_path()), js_api=api, width=1440, height=900,
                                   min_size=(1100, 700))
    api._window = window

    def on_loaded():
        # Dropped files' full paths are only exposed to a Python-side drop handler.
        window.dom.document.events.drop += DOMEventHandler(api._on_drop, prevent_default=True)

    window.events.loaded += on_loaded
    webview.start()


if __name__ == "__main__":
    main()

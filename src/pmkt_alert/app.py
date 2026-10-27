"""Desktop entry point: a native window (Edge WebView2 on Windows) showing ui/index.html."""
import sys
from pathlib import Path


def ui_path() -> Path:
    # One-file builds unpack data to sys._MEIPASS/pmkt_alert/ui (see pmkt_alert.spec).
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "pmkt_alert" / "ui" / "index.html"
    return Path(__file__).parent / "ui" / "index.html"


def main() -> None:
    if "--selfcheck" in sys.argv:  # used by CI on the built exe
        sys.exit(0 if ui_path().exists() else 1)
    import webview
    from webview.dom import DOMEventHandler

    from pmkt_alert.api import Api
    from pmkt_alert.store import Store, default_base

    api = Api(Store(default_base()))
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

"""Desktop entry point: a native window (Edge WebView2 on Windows) showing ui/index.html."""
from pathlib import Path

import webview

from pmkt_alert.api import Api
from pmkt_alert.store import Store, default_base

UI = Path(__file__).parent / "ui" / "index.html"


def main() -> None:
    api = Api(Store(default_base()))
    window = webview.create_window("PMKT Alert", url=str(UI), js_api=api, width=1440, height=900, min_size=(1100, 700))
    api._window = window
    webview.start()


if __name__ == "__main__":
    main()

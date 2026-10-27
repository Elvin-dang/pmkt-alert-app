import re
from pathlib import Path

from banned import BANNED_STRINGS
from pmkt_alert.api import Api

UI = Path(__file__).parents[1] / "src" / "pmkt_alert" / "ui"


def _ui_text():
    return "".join((UI / f).read_text(encoding="utf-8") for f in ("index.html", "app.js", "styles.css"))


def test_no_external_fonts_and_no_business_data():
    text = _ui_text()
    assert "fonts.googleapis.com" not in text and "http://" not in text
    for banned in BANNED_STRINGS:
        assert banned.lower() not in text.lower(), banned


def test_every_api_call_exists():
    js = (UI / "app.js").read_text(encoding="utf-8")
    called = set(re.findall(r"api\.(\w+)\(", js))
    public = {m for m in dir(Api) if not m.startswith("_")}
    assert called and called <= public, called - public


def test_fonts_bundled():
    css = (UI / "styles.css").read_text(encoding="utf-8")
    for url in re.findall(r"url\(([^)]+)\)", css):
        assert (UI / url.strip("'\"")).exists(), url

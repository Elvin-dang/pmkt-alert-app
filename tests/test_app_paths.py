import sys

from pmkt_alert.app import ui_path


def test_ui_path_from_package():
    assert ui_path().exists() and ui_path().name == "index.html"


def test_ui_path_in_onefile_bundle(tmp_path, monkeypatch):
    target = tmp_path / "pmkt_alert" / "ui" / "index.html"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ui_path() == target

import pytest

from pmkt_alert.changelog import notes_for, parse

TEXT = """# Changelog

## v0.1.4 – 27/10/2026
### Mới
- Cập nhật không còn mở cửa sổ terminal
### Sửa lỗi
- Lỗi khi file logic có ô trống

## v0.1.3 – 26/10/2026
- Icon mới
"""


def test_parse_sections():
    s = parse(TEXT)
    assert list(s) == ["0.1.4", "0.1.3"] and s["0.1.4"]["date"] == "27/10/2026"
    assert "### Mới" in s["0.1.4"]["notes"] and "terminal" in s["0.1.4"]["notes"] and "Icon" not in s["0.1.4"]["notes"]


def test_notes_for_tag_and_missing():
    assert "Icon mới" in notes_for(TEXT, "v0.1.3")
    with pytest.raises(KeyError):
        notes_for(TEXT, "v9.9.9")


def test_repo_changelog_has_current_version():
    from pathlib import Path
    from pmkt_alert.changelog import bundled_text
    text = bundled_text()
    assert text and parse(text)  # shipped with the app
    assert Path(__file__).parents[1].joinpath("CHANGELOG.md").read_text(encoding="utf-8") == text

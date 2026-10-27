"""CHANGELOG.md: the single source of release notes (GitHub release body + in-app 'Có gì mới')."""
import re
import sys
from pathlib import Path

_HEAD = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)\s*(?:[–-]\s*(.+?))?\s*$")


def parse(text: str) -> dict[str, dict]:
    out, current = {}, None
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            current = m.group(1)
            out[current] = {"date": (m.group(2) or "").strip(), "lines": []}
        elif current:
            out[current]["lines"].append(line)
    return {v: {"date": s["date"], "notes": "\n".join(s["lines"]).strip()} for v, s in out.items()}


def notes_for(text: str, tag: str) -> str:
    return parse(text)[tag.lstrip("v")]["notes"]


def bundled_text() -> str:
    """CHANGELOG.md next to the source tree (dev) or inside the one-file bundle."""
    here = Path(__file__).resolve()
    for p in (Path(getattr(sys, "_MEIPASS", "")) / "pmkt_alert" / "CHANGELOG.md", here.parents[2] / "CHANGELOG.md",
              here.parent / "CHANGELOG.md"):
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


if __name__ == "__main__":  # used by the release workflow: python -m pmkt_alert.changelog v0.1.4 > notes.md
    sys.stdout.reconfigure(encoding="utf-8")
    print(notes_for(Path("CHANGELOG.md").read_text(encoding="utf-8"), sys.argv[1]))

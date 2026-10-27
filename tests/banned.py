from pathlib import Path

_F = Path(__file__).parent / "fixtures" / "private" / "banned.txt"
BANNED_STRINGS = [s.strip() for s in _F.read_text(encoding="utf-8").splitlines() if s.strip()] if _F.exists() else []

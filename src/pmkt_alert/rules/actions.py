"""Activity Log → per-campaign actions, and tier 4 action status (port of Campaign_Alert AC–AI).
The log has no Amazon campaign_id, so campaigns are joined by normalized name."""
import re
import unicodedata
from datetime import date, datetime, timedelta

import pandas as pd

from . import ACTIONED, NOT_ACTIONED, OLD_ACTION

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_SUFFIX = re.compile(r"_\d{9,}$")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_name(name: str) -> str:
    s = str(name).strip().lower()
    while _SUFFIX.search(s):
        s = _SUFFIX.sub("", s)
    return s


def _parse_time(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    m = re.match(r"^\s*([A-Za-z]{3})\w*\s+(\d{1,2}),\s*(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})", str(v))
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    mon, d, y, hh, mm, ss = m.groups()
    return datetime(int(y), _MONTHS[mon.lower()], int(d), int(hh), int(mm), int(ss))


def _first_num(s) -> float | None:
    m = _NUM.search(str(s or "").replace(",", ""))
    return float(m.group()) if m else None


def _up_down(prefix: str, from_, to) -> str:
    a, b = _first_num(from_), _first_num(to)
    return f"{prefix} ↓" if a is not None and b is not None and b < a else f"{prefix} ↑"


def category(type_: str, action: str, from_: str, to: str) -> str:
    t = str(type_ or "")
    if t == "negativeTargeting":
        return "Negative"
    if str(action) == "create":
        return "Tạo mới"
    if t.endswith("Bid") or t.startswith("bidAdjustment"):
        return _up_down("Bid", from_, to)
    if t == "campaignDailyBudget":
        return _up_down("Budget", from_, to)
    if t.endswith("Status"):
        if "Paused" in str(to):
            return "Pause"
        if "Enabled" in str(to):
            return "Enable"
    return "Khác"


def _campaign_of(level) -> str | None:
    s = str(level or "")
    if not s.startswith("Campaign:"):
        return None
    return s[len("Campaign:"):].split(" | ")[0].strip()


def parse_activity(raw: pd.DataFrame) -> pd.DataFrame:
    rows, skipped, aliases = [], 0, {}
    for r in raw.itertuples(index=False):
        name = _campaign_of(r.level)
        if name is None:
            continue
        when = _parse_time(r.time)
        if when is None:
            skipped += 1
            continue
        if r.type == "campaignName":
            old, new = normalize_name(r.from_), normalize_name(r.to)
            aliases[old] = new
            aliases.setdefault(normalize_name(name), new)
        rows.append((normalize_name(name), when, category(r.type, r.action, r.from_, r.to), str(r.user or "").strip().lower()))

    def canonical(k: str) -> str:
        seen = set()
        while k in aliases and k not in seen and aliases[k] != k:
            seen.add(k)
            k = aliases[k]
        return k

    out = pd.DataFrame([(canonical(k), t.date(), t, c, u) for k, t, c, u in rows],
                       columns=["camp_key", "action_date", "time", "category", "user"]).sort_values("time")
    out = out.drop(columns="time").reset_index(drop=True)
    out.attrs["skipped"] = skipped
    out.attrs["aliases"] = {k: canonical(k) for k in aliases}
    return out


def _ascii(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def suggest_email_map(emails: list[str], pics: list[str]) -> dict[str, str]:
    candidates = {}
    for pic in pics:
        words = _ascii(pic).split()
        if words:
            candidates[words[-1] + "".join(w[0] for w in words[:-1])] = pic
    out = {}
    for e in emails:
        local = re.sub(r"\d+$", "", str(e).split("@")[0].lower())
        if local in candidates:
            out[e] = candidates[local]
    return out


def _check(l3d, l7d, ratio) -> str:
    if l3d is None:
        return "Chưa có sale trong L3D sau action → cân nhắc action thêm"
    if l7d is None:
        return f"ACoS L3D {l3d:.1%} (L7D chưa có sale để so)"
    if l3d <= l7d * ratio:
        return f"Đang cải thiện: ACoS L3D {l3d:.1%} vs L7D {l7d:.1%}"
    return f"Chưa cải thiện: ACoS L3D {l3d:.1%} vs L7D {l7d:.1%} → cân nhắc action thêm"


def _none(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def action_status(camp: pd.DataFrame, actions: pd.DataFrame, as_of: date, p: dict, key: str = "camp_key") -> pd.DataFrame:
    out = camp.copy()
    if key not in out.columns:
        aliases = actions.attrs.get("aliases", {})
        out[key] = [aliases.get(normalize_name(c), normalize_name(c)) for c in out["campaign"]]
    past = actions[actions["action_date"] <= as_of]
    last = past.groupby(key).tail(1).set_index(key) if len(past) else past.set_index(key)
    last_date = out[key].map(last["action_date"]) if len(last) else pd.Series(None, index=out.index)
    last_type = out[key].map(last["category"]) if len(last) else pd.Series(None, index=out.index)
    out["last_action_date"] = pd.Series([_none(d) for d in last_date], index=out.index, dtype=object)
    out["last_action_type"] = pd.Series([_none(t) for t in last_type], index=out.index, dtype=object)
    out["days_since"] = pd.Series([None if d is None else (as_of - d).days for d in out.last_action_date],
                                  index=out.index, dtype=object)
    status, due, check, final = [], [], [], []
    for r in out.itertuples():
        if r.sev in ("", "LOW") or pd.isna(r.sev):
            s = ""
        elif r.last_action_date is None:
            s = NOT_ACTIONED
        elif r.days_since < p["action_window"]:
            s = ACTIONED
        else:
            s = OLD_ACTION
        d = r.last_action_date + timedelta(days=int(p["followup_days"])) if s == ACTIONED else None
        c = _check(_none(r.l3d_acos), _none(r.l7d_acos), p["improving_ratio"]) if s in (ACTIONED, OLD_ACTION) else ""
        if s == NOT_ACTIONED:
            f = r.base_action
        elif s == ACTIONED:
            f = f"ĐÃ ACTION ({r.last_action_type} {r.last_action_date:%d/%m}) – follow up {d:%d/%m}"
        elif s == OLD_ACTION:
            f = f"ACTION CŨ ({r.last_action_date:%d/%m}) – alert còn → action lại: {r.base_action}"
        else:
            f = ""
        status.append(s), due.append(d), check.append(c), final.append(f)
    out["status"] = status
    out["followup_due"] = pd.Series(due, index=out.index, dtype=object)
    out["followup_check"] = check
    out["final_label"] = final
    return out

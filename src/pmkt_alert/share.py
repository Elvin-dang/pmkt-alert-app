"""What goes inside a .pmkt: the run (results, Claude output, team review), the logic file, and only the data
rows a Member's app needs for Evidence and the Dashboard (date windows of that run), as compressed JSON."""
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .loaders import Inputs
from .windows import Windows

TABLES = ("raw", "products", "kpi", "ineligible", "ads", "activity")


def _frame_bytes(df: pd.DataFrame) -> bytes:
    dates = [c for c in df.columns if len(df) and isinstance(df[c].dropna().iloc[0] if df[c].notna().any() else None, date)]
    out = df.copy()
    for c in dates:
        out[c] = out[c].map(lambda v: v.isoformat() if isinstance(v, date) else None)
    return json.dumps({"columns": list(out.columns), "dates": dates, "attrs": df.attrs,
                       "data": out.astype(object).where(out.notna(), None).values.tolist()},
                      ensure_ascii=False, default=str).encode("utf-8")


def _frame_from(data: bytes) -> pd.DataFrame:
    d = json.loads(data)
    df = pd.DataFrame(d["data"], columns=d["columns"])
    for c in d["dates"]:
        df[c] = df[c].map(lambda v: date.fromisoformat(v) if v else None)
    for c in df.columns:
        if c not in d["dates"] and df[c].map(lambda v: isinstance(v, (int, float)) or v is None).all() and df[c].notna().any():
            df[c] = pd.to_numeric(df[c])
    df.attrs = d.get("attrs", {})
    return df


def _since(df: pd.DataFrame, start: date) -> pd.DataFrame:
    return df[df["date"] >= start] if "date" in df.columns and len(df) else df


def pack_run(run: dict, inputs: Inputs, logic_path: Path) -> dict[str, bytes]:
    as_of = date.fromisoformat(run["result"]["as_of"])
    win = Windows(as_of)
    week_start = as_of - timedelta(days=as_of.weekday()) - timedelta(weeks=7)  # Dashboard: 8 weeks
    start = min(win.mtd[0], win.p7d[0], week_start)
    tables = {"raw": _since(inputs.raw, start), "products": inputs.products,
              "kpi": inputs.kpi[inputs.kpi["month"] == as_of.month], "ineligible": _since(inputs.ineligible, win.l7d[0]),
              "ads": _since(inputs.ads, min(win.mtd[0], win.p7d[0])), "activity": inputs.activity}
    files = {f"data/{k}.json": _frame_bytes(v) for k, v in tables.items()}
    files["run.json"] = json.dumps(run, ensure_ascii=False).encode("utf-8")
    files["logic.xlsx"] = Path(logic_path).read_bytes()
    files["meta.json"] = json.dumps({"sources": inputs.sources, "defind_text": inputs.defind_text,
                                     "event_days": {k.isoformat(): v for k, v in inputs.event_days.items()},
                                     "logic_name": Path(logic_path).name}, ensure_ascii=False).encode("utf-8")
    return files


def unpack_run(files: dict[str, bytes]) -> tuple[dict, Inputs, bytes, str]:
    meta = json.loads(files["meta.json"])
    t = {k: _frame_from(files[f"data/{k}.json"]) for k in TABLES}
    inputs = Inputs(t["raw"], t["products"], t["kpi"], t["ineligible"], t["ads"], t["activity"],
                    {date.fromisoformat(k): v for k, v in meta["event_days"].items()}, meta["defind_text"], meta["sources"])
    return json.loads(files["run.json"]), inputs, files["logic.xlsx"], meta["logic_name"]


def filter_run(run: dict, pic: str, scorecard_row: dict | None) -> dict:
    """Only what one PIC may see: their rows, their Claude output, the Department frame needed to read their
    score, and their own scorecard row (no ranking, no other PICs, no logic review, no data warnings)."""
    res = run["result"]
    mine = lambda rows: [r for r in rows if r.get("pic") == pic]  # noqa: E731
    result = {**res, "pl": mine(res["pl"]), "camp": mine(res["camp"]), "digest": mine(res["digest"]),
              "pics": mine(res.get("pics") or []), "issues": [], "logic_issues": [], "unreliable": False}
    ai = run.get("ai") or {}
    ai_part = {"claude_ok": ai.get("claude_ok"), "error": ai.get("error"), "review": [], "logic_eval": None,
               "per_pic": {pic: ai["per_pic"][pic]} if pic in (ai.get("per_pic") or {}) else {}}
    row = None
    if scorecard_row:
        row = {**scorecard_row, "rank": None}
    return {"run_id": run.get("run_id"), "result": result, "ai": ai_part, "team_review": None, "my_scorecard": row}


def filter_inputs(inputs: Inputs, run: dict, pic: str) -> Inputs:
    """Data rows for this PIC's own product lines / campaigns only."""
    pls = {r["pl"] for r in run["result"]["pl"] if r.get("pic") == pic}
    asins = set(inputs.products.loc[inputs.products["pl"].isin(pls), "asin"])
    keys = {r.get("camp_key") for r in run["result"]["camp"] if r.get("pic") == pic}
    from .rules.actions import _campaign_of, normalize_name
    act = inputs.activity
    if len(act):
        act = act[[normalize_name(_campaign_of(lv) or "") in keys for lv in act["level"]]]
    pick = lambda df: df[df["asin"].isin(asins)] if "asin" in df.columns else df  # noqa: E731
    return Inputs(pick(inputs.raw), pick(inputs.products), pick(inputs.kpi), pick(inputs.ineligible), pick(inputs.ads),
                  act, inputs.event_days, inputs.defind_text, inputs.sources)


def build_parts(run: dict, inputs: Inputs, logic_path: Path, members: list[dict], scorecard_rows: dict) -> dict:
    """{"lead": (files, []), "pic:X": (files, [member public keys of X])} for package.build."""
    from .identity import parse_member_code
    parts = {"lead": (pack_run(run, inputs, logic_path), [])}
    for pic in sorted({m["pic"] for m in members}):
        readers = [parse_member_code(m["code"]) for m in members if m["pic"] == pic]
        part_run = filter_run(run, pic, scorecard_rows.get(pic))
        parts[f"pic:{pic}"] = (pack_run(part_run, filter_inputs(inputs, run, pic), logic_path), readers)
    return parts

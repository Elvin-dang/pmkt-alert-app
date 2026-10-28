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

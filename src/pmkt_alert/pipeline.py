"""Runs tiers 0–4 on loaded inputs."""
import math
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from .aggregate import NO_PIC, asin_map, camp_frame, pl_frame
from .logic import Logic
from .rules.actions import action_status, parse_activity
from .rules.campaign import campaign
from .rules.dataq import Issue, data_check
from .rules.digest import digest
from .rules.pacing import pacing
from .rules.trend import trend
from .windows import Windows, default_as_of


@dataclass
class RunResult:
    as_of: date
    logic_version: int
    pl: pd.DataFrame
    camp: pd.DataFrame
    digest: pd.DataFrame
    issues: list[Issue]
    unreliable: bool


def apply_rules(pl: pd.DataFrame, camp: pd.DataFrame, actions: pd.DataFrame, logic: Logic, win: Windows,
                key: str = "camp_key") -> tuple[pd.DataFrame, pd.DataFrame]:
    p = logic.params
    pl = trend(pacing(pl, win.time_gone, p), p, logic.matrix)
    pl.insert(0, "unit_id", [f"pl:{x}" for x in pl["pl"]])
    camp = campaign(camp, pl, p, logic.k_by_type)
    camp = action_status(camp, actions, win.as_of, p, key=key)
    return pl, camp


def _between(df, span):
    return df[(df["date"] >= span[0]) & (df["date"] <= span[1])]


def run_rules(inputs, logic: Logic, as_of: date | None = None) -> RunResult:
    win = Windows(as_of or default_as_of(inputs))
    amap = asin_map(inputs.products, win.as_of)
    actions = parse_activity(inputs.activity)
    pl, camp = apply_rules(pl_frame(inputs, amap, win), camp_frame(inputs.ads, amap, win), actions, logic, win)

    ads_mtd = _between(inputs.ads, win.mtd).merge(amap[["asin", "pl"]], on="asin", how="left")
    unmapped = ads_mtd[ads_mtd["pl"].fillna("") == ""]
    spenders = camp[camp["l7d_spend"] > 0].groupby("camp_key").agg(campaign=("campaign", "first"),
                                                                    l7d_spend=("l7d_spend", "sum"))
    unmatched = spenders[~spenders.index.isin(set(actions["camp_key"]))].reset_index(drop=True)
    issues = data_check(
        unmapped_rows=len(unmapped), unmapped_spend=float(unmapped["spend"].sum()),
        ads_spend_mtd=float(ads_mtd["spend"].sum()), raw_spend_mtd=float(_between(inputs.raw, win.mtd)["spend"].sum()),
        unmatched_camps=unmatched, duplicates=amap.attrs.get("duplicates", 0),
        no_pic_pls=sorted(pl.loc[pl["pic"] == NO_PIC, "pl"]), log_skipped=actions.attrs.get("skipped", 0),
        log_empty=len(inputs.activity) == 0)
    unreliable = any(i.severity == "WARN" and i.code in ("UNMAPPED", "SPEND_GAP") for i in issues)
    return RunResult(win.as_of, logic.version, pl, camp, digest(pl, camp), issues, unreliable)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        return _clean(v.item())
    return v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def result_to_json(r: RunResult) -> dict:
    return {"as_of": r.as_of.isoformat(), "logic_version": r.logic_version, "pl": _records(r.pl),
            "camp": _records(r.camp), "digest": _records(r.digest),
            "issues": [{k: _clean(v) for k, v in asdict(i).items()} for i in r.issues], "unreliable": r.unreliable}

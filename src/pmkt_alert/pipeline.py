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
from .rules.score_v3 import department, score_rows
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
    model: str = "rules_v1"
    pics: pd.DataFrame | None = None  # score model: one scored row per PIC
    dept: dict | None = None  # score model: Department frame


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


SUM_COLS = ["target_gmv", "target_spend", "gmv_mtd", "spend_mtd", "ads_gmv_mtd", "l7d_spend", "p7d_spend",
            "l7d_ads_gmv", "p7d_ads_gmv", "l7d_gmv", "p7d_gmv", "camp_l7d_spend", "camp_l7d_clicks",
            "camp_l7d_sales", "camp_l7d_orders"]


def _score_model(inputs, logic: Logic, win: Windows, actions: pd.DataFrame):
    """Team v3: scope by Team Label, PIC from PMKT PIC_Final, Department frame, PIC + PL scores."""
    p = logic.params
    amap = asin_map(inputs.products, win.as_of, pic_col="PMKT PIC_Final")
    label = logic.texts.get("team_label", "")
    scoped = amap[amap["team"] == label] if label and "team" in amap.columns else amap
    scoped.attrs = amap.attrs
    pl = trend(pl_frame(inputs, scoped, win), p, logic.matrix)
    names = sorted(set(scoped["pic"]) - {NO_PIC})
    sums = pl.groupby("pic")[SUM_COLS].sum().reindex(names, fill_value=0.0).rename_axis("pic").reset_index()
    pics = trend(sums, p, logic.matrix)
    dept = department(pl, pics, p)
    pl = score_rows(pl, dept, win.time_gone, p)
    pl.insert(0, "unit_id", [f"pl:{x}" for x in pl["pl"]])
    pics = score_rows(pics, dept, win.time_gone, p)
    pics.insert(0, "unit_id", [f"pic:{x}" for x in pics["pic"]])
    camp = action_status(campaign(camp_frame(inputs.ads, scoped, win), pl, p, logic.k_by_type), actions, win.as_of, p)
    # data checks map against ALL teams: other teams' ASINs are out of scope, not unmapped
    return pl, camp, pics, dept, amap, {"out_of_scope": len(amap) - len(scoped), "scope_label": label,
                                        "in_scope": len(scoped)}


def run_rules(inputs, logic: Logic, as_of: date | None = None) -> RunResult:
    win = Windows(as_of or default_as_of(inputs))
    actions = parse_activity(inputs.activity)
    if logic.model == "score_v3":
        pl, camp, pics, dept, amap, scope = _score_model(inputs, logic, win, actions)
    else:
        amap = asin_map(inputs.products, win.as_of)
        pl, camp = apply_rules(pl_frame(inputs, amap, win), camp_frame(inputs.ads, amap, win), actions, logic, win)
        pics, dept, scope = None, None, {}

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
        log_empty=len(inputs.activity) == 0, no_targets=not (inputs.kpi["month"] == win.as_of.month).any(), **scope)
    unreliable = any(i.severity == "WARN" and i.code in ("UNMAPPED", "SPEND_GAP", "NO_TARGETS", "NO_SCOPE") for i in issues)
    return RunResult(win.as_of, logic.version, pl, camp, digest(pl, camp, pics), issues, unreliable, logic.model, pics, dept)


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
    return {"as_of": r.as_of.isoformat(), "logic_version": r.logic_version, "model": r.model, "pl": _records(r.pl),
            "camp": _records(r.camp), "digest": _records(r.digest),
            "pics": _records(r.pics) if r.pics is not None else [],
            "dept": {k: _clean(v) for k, v in r.dept.items()} if r.dept else None,
            "issues": [{k: _clean(v) for k, v in asdict(i).items()} for i in r.issues], "unreliable": r.unreliable}

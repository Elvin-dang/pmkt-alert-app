"""Reproduces Alert_Logic_System_Team_v3 (score model) from its own inputs. Needs the private workbook."""
from datetime import date, datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

from pmkt_alert.logic import load_logic
from pmkt_alert.rules.actions import action_status
from pmkt_alert.rules.campaign import campaign
from pmkt_alert.rules.digest import digest
from pmkt_alert.rules.score_v3 import department, score_rows
from pmkt_alert.rules.trend import trend
from pmkt_alert.xlsx import read_sheet

WB = Path(__file__).parent / "fixtures" / "private" / "Alert_Logic_System_Team_v3.xlsx"
if not WB.exists():
    pytest.skip("private v3 workbook not present", allow_module_level=True)

AS_OF = date(2026, 10, 19)
TG = 19 / 31
IN = {"Target GMV": "target_gmv", "Target Spend": "target_spend", "Actual GMV (MTD)": "gmv_mtd",
      "Actual Spend (MTD)": "spend_mtd", "Actual Ads GMV (MTD)": "ads_gmv_mtd", "L7D Spend": "l7d_spend",
      "P7D Spend": "p7d_spend", "L7D Ads GMV": "l7d_ads_gmv", "P7D Ads GMV": "p7d_ads_gmv",
      "L7D Total GMV": "l7d_gmv", "P7D Total GMV": "p7d_gmv"}
FACTORS = {"s1 vs target riêng": "s1", "s2 vs target Dept": "s2", "s3 ads dependency": "s3", "s4 trend TACoS": "s4",
           "s5 GMV pace": "s5", "s6 spend pace": "s6", "SCORE (−100…+100)": "score", "Excess$ vs target Dept": "excess_dept"}


@pytest.fixture(scope="module")
def lg():
    return load_logic(WB)


@pytest.fixture(scope="module")
def cfg():
    ws = openpyxl.load_workbook(WB, data_only=True)["Config"]
    return {r: ws[f"C{r}"].value for r in range(66, 76)}


def frame(sheet, key):
    df = read_sheet(WB, sheet, header_row=4)
    df = df[df[key].notna() & (df[key].astype(str).str.strip() != "")].reset_index(drop=True)
    inputs = df[list(IN)].rename(columns=IN).astype(float)
    return df, inputs


def blank(v):
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else v


@pytest.fixture(scope="module")
def dept(lg):
    sku = read_sheet(WB, "SKU_Data", header_row=4)
    sku = sku[sku["Trong phạm vi"] == 1]
    rows = pd.DataFrame({"target_gmv": sku["Target GMV"], "target_spend": sku["Target Spend"],
                         "gmv_mtd": sku["MTD Total GMV"], "spend_mtd": sku["MTD Spend"], "ads_gmv_mtd": sku["MTD Ads GMV"]}).astype(float)
    pic_df, pic_in = frame("PIC_Alert", "SEM PIC")
    return department(rows, pd.DataFrame({"pic": pic_df["SEM PIC"], "gmv_mtd": pic_in["gmv_mtd"]}), lg.params)


def test_department_matches_config(dept, cfg):
    assert dept["target_gmv"] == pytest.approx(cfg[66]) and dept["target_spend"] == pytest.approx(cfg[67])
    assert dept["target_tacos"] == pytest.approx(cfg[68]) and dept["actual_gmv"] == pytest.approx(cfg[69])
    assert dept["actual_spend"] == pytest.approx(cfg[70]) and dept["actual_tacos"] == pytest.approx(cfg[71])
    assert dept["coverage"] == pytest.approx(cfg[72]) and dept["regime"] == cfg[73]
    assert dept["benchmark"] == pytest.approx(cfg[74]) and dept["sd_threshold"] == cfg[75]


@pytest.mark.parametrize("sheet,key", [("PL_Alert", "Product Line"), ("PIC_Alert", "SEM PIC")])
def test_scores_codes_and_reasons(lg, dept, sheet, key):
    df, inputs = frame(sheet, key)
    out = score_rows(trend(inputs, lg.params, lg.matrix), dept, TG, lg.params)
    for col, ours in FACTORS.items():
        theirs = [None if blank(v) == "" else float(v) for v in df[col]]
        mine = [None if v is None else float(v) for v in out[ours]]
        assert all((a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-6)
                   for a, b in zip(mine, theirs)), (sheet, col)
    assert list(out.base_code) == list(df["Base code"]), sheet
    assert list(out.pacing_action) == list(df["ACTION CODE"]), sheet
    assert [blank(v) for v in out.pacing_sev] == [blank(v) for v in df["Severity"]], sheet
    assert [blank(v) for v in out.trend_label] == [blank(v) for v in df["TREND LABEL (L7D)"]], sheet
    mism = [(a, b) for a, b in zip(out.pacing_reason, [blank(v) for v in df["Lý do"]]) if a != b]
    assert not mism, mism[:3]


def test_campaigns_and_digest(lg, dept):
    pl_df, pl_in = frame("PL_Alert", "Product Line")
    pl = score_rows(trend(pl_in, lg.params, lg.matrix), dept, TG, lg.params)
    pl["pl"], pl["pic"] = pl_df["Product Line"], pl_df["SEM PIC"]
    for a, b in (("ads_camp L7D Spend", "camp_l7d_spend"), ("ads_camp L7D Clicks", "camp_l7d_clicks"),
                 ("ads_camp L7D Sales", "camp_l7d_sales"), ("ads_camp L7D Orders", "camp_l7d_orders")):
        pl[b] = pl_df[a].astype(float)
    c_df = read_sheet(WB, "Campaign_Alert", header_row=4)
    c_df = c_df[c_df["Campaign ID"].notna()].reset_index(drop=True)
    cols = {"Campaign": "campaign", "Campaign ID": "campaign_id", "Product Line": "pl", "Type": "type",
            "L7D Spend": "l7d_spend", "L7D Clicks": "l7d_clicks", "L7D Sales": "l7d_sales", "L7D Orders": "l7d_orders",
            "P7D Spend": "p7d_spend", "P7D Sales": "p7d_sales", "L3D Spend": "l3d_spend", "L3D Sales": "l3d_sales"}
    camp_in = c_df[list(cols)].rename(columns=cols)
    for c in camp_in.columns[4:]:
        camp_in[c] = camp_in[c].astype(float)
    camp_in["campaign_id"] = camp_in["campaign_id"].astype(str)
    log = read_sheet(WB, "Action_Log", header_row=4)
    log = log[log["campaign_id"].notna() & (log["campaign_id"].astype(str).str.strip() != "")]
    acts = pd.DataFrame({"campaign_id": log["campaign_id"].astype(str),
                         "action_date": [d.date() if isinstance(d, datetime) else d for d in log["log_date"]],
                         "category": log["action_type"], "user": log["PIC"]})
    camp = action_status(campaign(camp_in, pl, lg.params, lg.k_by_type), acts, AS_OF, lg.params, key="campaign_id")
    assert list(camp.base_action) == list(c_df["Base action"])
    assert [blank(v) for v in camp.sev] == [blank(v) for v in c_df["Severity"]]
    assert [blank(v) for v in camp.status] == [blank(v) for v in c_df["ACTION STATUS"]]
    assert np.allclose(camp.excess.astype(float), c_df["Excess spend $"].astype(float), atol=0.01)
    d = digest(pl, camp).set_index("pic")
    dg = read_sheet(WB, "PIC_Digest", header_row=6)
    dg = dg[dg["PIC"].notna()].head(7).set_index("PIC")
    for pic, r in dg.iterrows():
        mine = d.loc[pic] if pic in d.index else None
        got = (0, 0, 0, 0, 0, 0, 0.0) if mine is None else (mine.pl_high, mine.pl_med, mine.pl_trend_review,
                                                             mine.camp_high, mine.camp_med, mine.camp_followup, mine.excess_new)
        want = (r["PL HIGH"], r["PL MED"], r["PL trend cần review"], r["Camp HIGH cần action"], r["Camp MED cần action"],
                r["Camp đã action – follow up"], r["Excess spend cần action ($)"])
        assert got[:6] == tuple(int(x) for x in want[:6]) and got[6] == pytest.approx(want[6]), pic

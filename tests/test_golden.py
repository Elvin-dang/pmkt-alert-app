"""Reproduces Alert_Logic_Ver 1 from its own pasted inputs. Needs the private workbook (git-ignored)."""
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pmkt_alert.logic import load_logic
from pmkt_alert.pipeline import apply_rules
from pmkt_alert.rules.digest import digest
from pmkt_alert.windows import Windows
from pmkt_alert.xlsx import read_sheet

PRIVATE = Path(__file__).parent / "fixtures" / "private"
WB = PRIVATE / "Alert_Logic_Ver 1.xlsx"
if not WB.exists():
    pytest.skip("private golden workbook not present", allow_module_level=True)

PL_COLS = {"Product Line": "pl", "SEM PIC": "pic", "Target GMV": "target_gmv", "Target Spend": "target_spend",
           "Target TACoS": "target_tacos", "Actual GMV (MTD)": "gmv_mtd", "Actual Spend (MTD)": "spend_mtd",
           "L7D Spend": "l7d_spend", "P7D Spend": "p7d_spend", "L7D Ads GMV": "l7d_ads_gmv", "P7D Ads GMV": "p7d_ads_gmv",
           "L7D Total GMV": "l7d_gmv", "P7D Total GMV": "p7d_gmv", "ads_camp L7D Spend": "camp_l7d_spend",
           "ads_camp L7D Clicks": "camp_l7d_clicks", "ads_camp L7D Sales": "camp_l7d_sales",
           "ads_camp L7D Orders": "camp_l7d_orders"}
CAMP_COLS = {"Campaign": "campaign", "Campaign ID": "campaign_id", "Product Line": "pl", "Type": "type",
             "L7D Spend": "l7d_spend", "L7D Clicks": "l7d_clicks", "L7D Sales": "l7d_sales", "L7D Orders": "l7d_orders",
             "P7D Spend": "p7d_spend", "P7D Sales": "p7d_sales", "L3D Spend": "l3d_spend", "L3D Sales": "l3d_sales"}


def rename(df, cols):
    out = df[list(cols)].rename(columns=cols)
    for c in out.columns:
        if c not in ("pl", "pic", "campaign", "campaign_id", "type"):
            out[c] = out[c].astype(float)
    return out


def log_by_id(log):
    log = log[log["campaign_id"].notna() & (log["campaign_id"].astype(str).str.strip() != "")]
    return pd.DataFrame({"campaign_id": log["campaign_id"].astype(str),
                         "action_date": [d.date() if isinstance(d, datetime) else d for d in log["log_date"]],
                         "category": log["action_type"], "user": log["PIC"]})


def blank(s):
    # Excel's INDEX over an empty Matrix_PL cell yields 0; the app uses "" for "no label".
    return [("" if v is None or v == 0 or (isinstance(v, float) and np.isnan(v)) else v) for v in s]


def test_golden_reproduces_workbook():
    lg = load_logic(WB)
    pl_in = read_sheet(WB, "PL_Alert", header_row=4)
    camp_in = read_sheet(WB, "Campaign_Alert", header_row=4)
    log_in = read_sheet(WB, "Action_Log", header_row=4)
    pl, camp = apply_rules(rename(pl_in, PL_COLS), rename(camp_in, CAMP_COLS).assign(campaign_id=lambda d: d.campaign_id.astype(str)),
                           log_by_id(log_in), lg, Windows(date(2026, 10, 19)), key="campaign_id")
    assert list(pl.pacing_action) == list(pl_in["PACING ACTION"])
    assert list(pl.pacing_sev) == list(pl_in["Severity (pacing)"])
    assert blank(pl.trend_label) == blank(pl_in["TREND LABEL (L7D)"])
    assert list(camp.min_clicks) == list(camp_in["Min clicks"].astype(int))
    assert list(camp.base_action) == list(camp_in["Base action"])
    assert blank(camp.camp_trend) == blank(camp_in["Trend"])
    assert blank(camp.sev) == blank(camp_in["Severity"])
    assert blank(camp.status) == blank(camp_in["ACTION STATUS"])
    assert blank(camp.final_label) == blank(camp_in["FINAL LABEL"])
    assert np.allclose(camp.excess.astype(float), camp_in["Excess spend $"].astype(float), atol=0.01)
    d = digest(pl, camp).set_index("pic").iloc[0]
    assert (d.pl_high, d.pl_med, d.pl_trend_review, d.camp_high, d.camp_med, d.camp_followup) == (7, 5, 4, 5, 27, 4)
    assert round(d.excess_new, 2) == 615.72

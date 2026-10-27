"""Per-PIC counts (port of PIC_Digest C–I)."""
import pandas as pd

from . import NOT_ACTIONED, OLD_ACTION, ACTIONED

COLS = ["pic", "pl_high", "pl_med", "pl_trend_review", "camp_high", "camp_med", "camp_followup", "excess_new"]


def digest(pl: pd.DataFrame, camp: pd.DataFrame) -> pd.DataFrame:
    pics = sorted(set(pl["pic"]) | set(camp["pic"]))
    new = camp["status"].isin([NOT_ACTIONED, OLD_ACTION])
    rows = []
    for pic in pics:
        p = pl[pl["pic"] == pic]
        c = camp["pic"] == pic
        rows.append([pic, int((p.pacing_sev == "HIGH").sum()), int((p.pacing_sev == "MED").sum()),
                     int(p.trend_label.fillna("").str.startswith("REVIEW").sum()),
                     int((c & new & (camp.sev == "HIGH")).sum()), int((c & new & (camp.sev == "MED")).sum()),
                     int((c & (camp.status == ACTIONED)).sum()), float(camp.loc[c & new, "excess"].sum())])
    return pd.DataFrame(rows, columns=COLS)

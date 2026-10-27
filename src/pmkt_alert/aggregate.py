"""ASIN → SKU → Product Line (old) → PIC mapping and the PL / (campaign, PL) frames the rules run on."""
from datetime import date

import pandas as pd

from .windows import Windows

NO_PIC = "Chưa có PIC"


def pic_column(columns: list[str], as_of: date) -> str:
    col = f"PIC {as_of:%b}"
    return col if col in columns else "PMKT PIC_Final"


def asin_map(products: pd.DataFrame, as_of: date) -> pd.DataFrame:
    col = pic_column(list(products.columns), as_of)
    df = products.assign(_active=(products["status"] == "Active").astype(int), _order=range(len(products)))
    df = df.sort_values(["_active", "_order"], ascending=[False, True])
    deduped = df.drop_duplicates("asin")
    pic = deduped[col] if col in deduped.columns else pd.Series("", index=deduped.index)
    out = pd.DataFrame({"asin": deduped["asin"], "sku": deduped["sku"], "pl": deduped["pl"],
                        "pic": pic.replace("", NO_PIC)}).sort_index().reset_index(drop=True)
    out.attrs["duplicates"] = len(products) - len(deduped)
    return out


def _between(df: pd.DataFrame, span: tuple[date, date]) -> pd.DataFrame:
    return df[(df["date"] >= span[0]) & (df["date"] <= span[1])]


def _sum_by_pl(df: pd.DataFrame, amap: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    m = df.merge(amap[["asin", "pl"]], on="asin")
    m = m[m["pl"] != ""]
    return m.groupby("pl")[list(cols)].sum().rename(columns=cols)


def pl_frame(inputs, amap: pd.DataFrame, win: Windows) -> pd.DataFrame:
    raw, ads = inputs.raw, inputs.ads
    parts = [
        _sum_by_pl(_between(raw, win.mtd), amap, {"gmv": "gmv_mtd", "spend": "spend_mtd"}),
        _sum_by_pl(_between(raw, win.l7d), amap, {"spend": "l7d_spend", "ads_gmv": "l7d_ads_gmv", "gmv": "l7d_gmv"}),
        _sum_by_pl(_between(raw, win.p7d), amap, {"spend": "p7d_spend", "ads_gmv": "p7d_ads_gmv", "gmv": "p7d_gmv"}),
        _sum_by_pl(_between(ads, win.l7d), amap, {"spend": "camp_l7d_spend", "clicks": "camp_l7d_clicks",
                                                  "sales": "camp_l7d_sales", "orders": "camp_l7d_orders"}),
        _sum_by_pl(inputs.kpi[inputs.kpi["month"] == win.as_of.month], amap,
                   {"gmv": "target_gmv", "spend": "target_spend"}),
    ]
    pl = pd.concat(parts, axis=1).fillna(0.0)
    pl["target_tacos"] = (pl["target_spend"] / pl["target_gmv"]).where(pl["target_gmv"] != 0, 0.0)
    pics = amap[amap["pl"] != ""].groupby("pl")["pic"].agg(
        lambda s: s[s != NO_PIC].mode().iloc[0] if (s != NO_PIC).any() else NO_PIC)
    pl["pic"] = pics.reindex(pl.index).fillna(NO_PIC)
    keep = (pl[["target_gmv", "target_spend", "gmv_mtd", "spend_mtd", "l7d_spend", "p7d_spend",
                "l7d_gmv", "p7d_gmv"]] != 0).any(axis=1)
    pl = pl[keep].rename_axis("pl").reset_index()
    cols = ["pl", "pic", "target_gmv", "target_spend", "target_tacos", "gmv_mtd", "spend_mtd", "l7d_spend",
            "p7d_spend", "l7d_ads_gmv", "p7d_ads_gmv", "l7d_gmv", "p7d_gmv", "camp_l7d_spend", "camp_l7d_clicks",
            "camp_l7d_sales", "camp_l7d_orders"]
    return pl[cols]


def camp_frame(ads: pd.DataFrame, amap: pd.DataFrame, win: Windows) -> pd.DataFrame:
    recent = _between(ads, (win.p7d[0], win.as_of)).merge(amap[["asin", "pl"]], on="asin")
    recent = recent[recent["pl"] != ""]
    keys = ["campaign_id", "pl"]

    def window(span, cols):
        part = _between(recent, span)
        return part.groupby(keys)[list(cols)].sum().rename(columns=cols)

    out = pd.concat([
        window(win.l7d, {"spend": "l7d_spend", "clicks": "l7d_clicks", "sales": "l7d_sales", "orders": "l7d_orders"}),
        window(win.p7d, {"spend": "p7d_spend", "sales": "p7d_sales"}),
        window(win.l3d, {"spend": "l3d_spend", "sales": "l3d_sales"}),
    ], axis=1).fillna(0.0).reset_index()
    latest = recent.sort_values("date").groupby("campaign_id").last()
    out["campaign"] = out["campaign_id"].map(latest["campaign"])
    out["type"] = out["campaign_id"].map(latest["type"])
    return out[["campaign", "campaign_id", "pl", "type", "l7d_spend", "l7d_clicks", "l7d_sales", "l7d_orders",
                "p7d_spend", "p7d_sales", "l3d_spend", "l3d_sales"]]

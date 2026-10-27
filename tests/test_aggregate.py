from datetime import date

from factory import FACTORY_DAILY_GMV, FACTORY_DAILY_SPEND, FACTORY_SPLIT_CAMPAIGN_ID
from pmkt_alert.aggregate import asin_map, camp_frame, pic_column, pl_frame
from pmkt_alert.windows import Windows, default_as_of


def test_windows():
    w = Windows(date(2026, 10, 19))
    assert w.l7d == (date(2026, 10, 13), date(2026, 10, 19)) and w.p7d == (date(2026, 10, 6), date(2026, 10, 12))
    assert w.l3d == (date(2026, 10, 17), date(2026, 10, 19)) and w.mtd == (date(2026, 10, 1), date(2026, 10, 19))
    assert w.days_in_month == 31 and round(w.time_gone, 4) == 0.6129


def test_early_month_windows_use_only_current_month_for_mtd(loaded):
    w = Windows(date(2026, 10, 3))
    pl = pl_frame(loaded, asin_map(loaded.products, w.as_of), w).set_index("pl")
    alpha = pl.loc["PL Alpha"]
    assert alpha.gmv_mtd == FACTORY_DAILY_GMV["PL Alpha"] * 3
    assert alpha.l7d_spend == FACTORY_DAILY_SPEND["PL Alpha"] * 7  # reaches into September
    assert alpha.target_gmv == 10000 and alpha.target_spend == 600 and round(alpha.target_tacos, 4) == 0.06
    assert round(w.time_gone, 4) == round(3 / 31, 4)


def test_pic_column():
    assert pic_column(["PIC Oct", "PMKT PIC_Final"], date(2026, 10, 1)) == "PIC Oct"
    assert pic_column(["PIC Oct", "PMKT PIC_Final"], date(2026, 11, 1)) == "PMKT PIC_Final"


def test_dedupe_and_unassigned(loaded):
    m = asin_map(loaded.products, date(2026, 10, 19))
    assert m.asin.is_unique and m.attrs["duplicates"] == 1
    assert m.set_index("asin").loc["B000000001"].pl == "PL Alpha"  # Active row wins
    assert "Chưa có PIC" in set(m.pic)


def test_pl_frame_pic_and_camp_cols(loaded):
    w = Windows(date(2026, 10, 19))
    pl = pl_frame(loaded, asin_map(loaded.products, w.as_of), w).set_index("pl")
    assert pl.loc["PL Delta"].pic == "Chưa có PIC" and pl.loc["PL Gamma"].pic == "PIC B"
    assert pl.loc["PL Gamma"].target_gmv == 0 and pl.loc["PL Gamma"].l7d_spend == (10 + 2 + 3) * 7
    assert pl.loc["PL Alpha"].camp_l7d_spend == (5 + 4) * 7 and pl.loc["PL Alpha"].camp_l7d_orders == 7


def test_campaign_split_by_pl(loaded):
    c = camp_frame(loaded.ads, asin_map(loaded.products, date(2026, 10, 19)), Windows(date(2026, 10, 19)))
    split = c[c.campaign_id == FACTORY_SPLIT_CAMPAIGN_ID]
    assert set(split.pl) == {"PL Alpha", "PL Beta"}
    assert split.l7d_spend.tolist() == [28.0, 28.0] and split.l3d_spend.tolist() == [12.0, 12.0]
    assert "100000000000004" not in set(c.campaign_id)  # orphan asin excluded


def test_default_as_of(loaded):
    assert default_as_of(loaded) == date(2026, 10, 19)

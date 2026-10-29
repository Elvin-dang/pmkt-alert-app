"""Inventory guard (logic v4, Config K / tier 2B). Stock: Inventory AMZ; units sold: raw ordered_units (3/day/ASIN)."""
from datetime import date

import pandas as pd
import pytest

from factory import make_all_v4, make_data_workbook
from pmkt_alert.loaders import detect_inputs, load_inputs
from pmkt_alert.logic import DEFAULT_INV, load_logic
from pmkt_alert.pipeline import run_rules
from pmkt_alert.rules.inventory import (CAMP_HOLD_LOW, CAMP_PAUSE_OOS, EXCESS, L_ATTN, L_CRIT, L_EXCESS, LOW, NORMAL, OUT,
                                        WAIT_STOCK, guard_pl, sku_cover)


@pytest.fixture(scope="module")
def v4(tmp_path_factory):
    files = make_all_v4(tmp_path_factory.mktemp("inv"))
    roles = detect_inputs(list(files.values()))
    return files, load_inputs(roles), load_logic(files["logic"])


def test_sku_status_from_days_of_stock(v4):
    _, inp, _ = v4
    cover, info = sku_cover(inp.inventory, inp.raw, ["B000000001", "B000000002", "B000000003", "B000000004", "B000000005"],
                            date(2026, 10, 19), DEFAULT_INV)
    st = dict(zip(cover["asin"], cover["inv_status"]))
    assert st == {"B000000001": OUT, "B000000002": LOW, "B000000003": EXCESS, "B000000004": NORMAL, "B000000005": EXCESS}
    days = dict(zip(cover["asin"], cover["days_left"]))
    assert days["B000000002"] == pytest.approx(20 / 3) and info == {"missing": [], "stale": False, "latest": date(2026, 10, 19)}


def test_no_sales_is_normal_and_missing_stock_is_unknown(v4):
    _, inp, _ = v4
    raw = inp.raw.copy()
    raw.loc[raw["asin"] == "B000000004", "units"] = 0
    cover, info = sku_cover(inp.inventory, raw, ["B000000004", "B000000009"], date(2026, 10, 19), DEFAULT_INV)
    assert dict(zip(cover["asin"], cover["inv_status"])) == {"B000000004": NORMAL, "B000000009": None}
    assert info["missing"] == ["B000000009"]


def test_pl_guard_turns_scale_up_into_wait_for_stock():
    pl = pd.DataFrame([{"pl": "A", "pacing_action": "SCALE UP", "pacing_sev": "MED", "pacing_reason": "r", "inv_level": L_CRIT,
                        "trend_label": "REVIEW ADS", "trend_action": "Soát ads"},
                       {"pl": "B", "pacing_action": "SCALE UP", "pacing_sev": "MED", "pacing_reason": "r", "inv_level": L_EXCESS,
                        "trend_label": "", "trend_action": ""},
                       {"pl": "C", "pacing_action": "SCALE DOWN", "pacing_sev": "HIGH", "pacing_reason": "r", "inv_level": L_ATTN,
                        "trend_label": "REVIEW SKU", "trend_action": "Xem SKU"}])
    out = guard_pl(pl)
    assert list(out["pacing_action"]) == [WAIT_STOCK, "SCALE UP", "SCALE DOWN"]
    assert "Kiểm tra tồn kho trước" in out.loc[0, "trend_action"] and "Kiểm tra tồn kho trước" in out.loc[2, "trend_action"]
    assert "kế hoạch nhập hàng" in out.loc[0, "pacing_reason"]


def test_full_run_applies_the_guard(v4):
    _, inp, logic = v4
    r = run_rules(inp, logic, date(2026, 10, 19))
    lv = dict(zip(r.pl["pl"], r.pl["inv_level"]))
    assert lv["PL Alpha"] == L_CRIT and lv["PL Gamma"] == L_EXCESS
    camps = {c: (a, n) for c, a, n in zip(r.camp["campaign"], r.camp["base_action"], r.camp["inv_note"])}
    alpha = next(v for k, v in camps.items() if k.startswith("Camp Alpha"))
    assert alpha[0] == CAMP_PAUSE_OOS and next(s for c, s in zip(r.camp["campaign"], r.camp["sev"]) if c.startswith("Camp Alpha")) == "HIGH"
    gamma = next(v for k, v in camps.items() if k.startswith("Camp Gamma"))
    assert "dư tồn" in gamma[1]
    split = next(v for k, v in camps.items() if k.startswith("Camp Split"))
    assert split[0] != CAMP_PAUSE_OOS and (split[0] == CAMP_HOLD_LOW or not split[0].startswith(("SCALE UP", "MAINTAIN/PUSH")))
    assert not [i for i in r.issues if i.code.startswith("INV_")]


def test_stale_stock_warns_and_skips_the_guard(tmp_path, v4):
    files, _, logic = v4
    stale = make_data_workbook(tmp_path / "data.xlsx", stock_date=date(2026, 10, 10))
    inp = load_inputs(detect_inputs([stale, files["activity"], files["logic"]]))
    r = run_rules(inp, logic, date(2026, 10, 19))
    assert any(i.code == "INV_STALE" and i.severity == "WARN" for i in r.issues)
    assert r.pl["inv_level"].isna().all() and CAMP_PAUSE_OOS not in set(r.camp["base_action"])

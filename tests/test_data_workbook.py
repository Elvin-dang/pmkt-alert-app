"""v4 inputs: one data workbook (all tables) + Activity Log + Logic (no Defind)."""
from datetime import date

import pytest

from factory import INVENTORY, make_all_v4, make_data_workbook
from pmkt_alert.loaders import InputError, detect_inputs, load_inputs
from pmkt_alert.logic import load_logic


@pytest.fixture(scope="module")
def v4(tmp_path_factory):
    return make_all_v4(tmp_path_factory.mktemp("v4"))


def test_detects_data_activity_logic_without_defind(v4):
    roles = detect_inputs(list(v4.values()))
    assert roles["tracker"] == roles["ads"] == v4["data"]
    assert roles["activity"] == v4["activity"] and roles["logic"] == v4["logic"] and "defind" not in roles


def test_loads_the_new_tables(v4):
    inp = load_inputs(detect_inputs(list(v4.values())))
    assert set(inp.inventory["asin"]) == set(INVENTORY) and inp.inventory["date"].max() == date(2026, 10, 19)
    assert dict(zip(inp.kpi["asin"], inp.kpi["stock"]))["B000000002"] == INVENTORY["B000000002"]
    assert "units" in inp.raw.columns and "ads_units" in inp.raw.columns
    c = inp.contrib
    assert round(sum(v["gmv"] for v in c.values()), 6) == 1 and c[date(2026, 10, 1)]["ppc"] == pytest.approx(0.05)
    assert inp.products.loc[inp.products["sku"] == "S006", "status"].iloc[0] == "Inactive"
    assert "lifecycle" in inp.products.columns


def test_campaign_id_is_trailing_number_of_name(v4):
    inp = load_inputs(detect_inputs(list(v4.values())))
    for name, cid in zip(inp.ads["campaign"], inp.ads["campaign_id"]):
        tail = name.rsplit("_", 1)[-1]
        assert cid == (tail if tail.isdigit() else name)


def test_logic_v4_reads_matrix_alias_and_inventory_params(v4):
    lg = load_logic(v4["logic"])
    assert lg.model == "score_v3" and len(lg.matrix) == 27
    p = lg.params
    assert (p["inv_low_days"], p["inv_high_days"], p["inv_incoming_days"], p["inv_sales_days"]) == (14, 90, 7, 7)
    assert (p["inv_attention"], p["inv_critical"], p["inv_excess"], p["inv_camp_block"], p["inv_stale_days"]) == (0.2, 0.5, 0.5, 0.5, 2)
    assert not [i for i in lg.issues if i["hint"] == "error"]


def test_missing_column_stops_with_location(tmp_path, v4):
    bad = make_data_workbook(tmp_path / "data.xlsx", drop_column=("ads_camp", "spend_usd"))
    with pytest.raises(InputError) as e:
        load_inputs(detect_inputs([bad, v4["activity"], v4["logic"]]))
    loc = e.value.location
    assert loc["file"] == "data.xlsx" and loc["sheet"] == "ads_camp" and loc["columns"] == ["spend_usd"] and loc["row"] == 1
    assert "spend_usd" in str(e.value)

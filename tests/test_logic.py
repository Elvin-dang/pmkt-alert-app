import pytest

from factory import make_logic
from pmkt_alert.logic import LogicError, load_logic, version_from_name, write_logic_version
from pmkt_alert.xlsx import read_sheet


def test_loads_params_by_label_not_position(tmp_path):
    p = make_logic(tmp_path / "Alert_Logic_Ver 1.xlsx", insert_blank_rows_at=10)
    lg = load_logic(p)
    assert lg.version == 1
    assert lg.params["camp_cut"] == 1.15 and lg.params["trend_acos"] == 0.2
    assert lg.params["camp_optimize"] == 1.3 and lg.params["spend_pace_low"] == 0.9
    assert lg.k_by_type == {"SPS_PRODUCTS": 3, "SPS_BRANDS": 3, "SPS_DISPLAY": 5}
    assert len(lg.matrix) == 27 and lg.matrix["F|F|F"][0] == "" and lg.matrix["D|D|D"][0] == "SCALE"
    assert "pacing" in lg.tiers_text


def test_missing_param_raises(tmp_path):
    p = make_logic(tmp_path / "x.xlsx", drop="min_clicks")
    with pytest.raises(LogicError, match="min_clicks"):
        load_logic(p)


def test_version_from_name():
    assert version_from_name("Alert_Logic_Ver 12.xlsx") == 12 and version_from_name("logic.xlsx") == 1


def test_write_version(tmp_path):
    src = make_logic(tmp_path / "Alert_Logic_Ver 1.xlsx")
    out = write_logic_version(load_logic(src), {"camp_cut": 1.25, "matrix:U|F|F": "REVIEW ADS"}, "CUT 1.15→1.25", tmp_path / "out")
    assert out.name == "Alert_Logic_Ver 2.xlsx"
    new = load_logic(out)
    assert new.params["camp_cut"] == 1.25 and new.matrix["U|F|F"][0] == "REVIEW ADS" and new.version == 2
    assert load_logic(src).params["camp_cut"] == 1.15
    assert "CUT 1.15→1.25" in str(read_sheet(out, "README_Flow", header_row=1).to_dict())

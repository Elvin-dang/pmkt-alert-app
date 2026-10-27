import pytest

from factory import make_logic, make_logic_v3
from pmkt_alert.logic import DEFAULT_PARAMS, load_logic


def _codes(lg):
    return {(i["code"], i.get("key")) for i in lg.issues}


def test_v1_file_has_no_issues(tmp_path):
    lg = load_logic(make_logic(tmp_path / "Alert_Logic_Ver 1.xlsx"))
    assert lg.issues == [] and lg.params == DEFAULT_PARAMS


def test_v3_layout_parses_by_label_and_reports_missing(tmp_path):
    lg = load_logic(make_logic_v3(tmp_path / "Alert_Logic_System_Team_v3.xlsx"))
    assert lg.version == 3
    assert lg.params["trend_acos"] == 0.25 and lg.params["camp_cut"] == 1.2 and lg.k_by_type["SPS_DISPLAY"] == 5
    assert lg.cells["camp_cut"].startswith("Config!C")
    missing = {i["key"] for i in lg.issues if i["code"] == "MISSING"}
    assert missing == {"gmv_pace_low", "spend_pace_low", "spend_pace_high", "tacos_over"}
    assert lg.params["gmv_pace_low"] == DEFAULT_PARAMS["gmv_pace_low"]  # fallback keeps the run going
    assert all(i["used"] is not None for i in lg.issues if i["code"] == "MISSING")
    unused = [i for i in lg.issues if i["code"] == "UNUSED"]
    assert any("w1" in i["label"] for i in unused) and not any(i["label"].startswith("Giá trị") for i in unused)


def test_blank_value_falls_back_and_is_reported(tmp_path):
    lg = load_logic(make_logic_v3(tmp_path / "v3.xlsx", blank="Sàn click tối thiểu"))
    issue = next(i for i in lg.issues if i.get("key") == "min_clicks")
    assert issue["code"] == "BLANK" and issue["cell"].startswith("Config!C") and lg.params["min_clicks"] == 15


def test_fallback_prefers_previous_good_logic(tmp_path):
    prev = load_logic(make_logic(tmp_path / "Alert_Logic_Ver 1.xlsx"))
    prev.params["gmv_pace_low"] = 0.7
    lg = load_logic(make_logic_v3(tmp_path / "v3.xlsx"), fallback=prev)
    assert lg.params["gmv_pace_low"] == 0.7
    assert next(i for i in lg.issues if i.get("key") == "gmv_pace_low")["used_from"] == "Alert_Logic_Ver 1.xlsx"


def test_bad_matrix_label_and_range_checks(tmp_path):
    p = make_logic_v3(tmp_path / "v3.xlsx", bad_matrix=True)
    lg = load_logic(p)
    bad = next(i for i in lg.issues if i["code"] == "MATRIX_LABEL")
    assert bad["key"] == "matrix:U|U|U" and bad["cell"].startswith("Matrix_PL!F") and lg.matrix["U|U|U"][0] == "REVIEW ADS"


def test_out_of_range_reported(tmp_path):
    import openpyxl
    p = make_logic_v3(tmp_path / "v3.xlsx")
    wb = openpyxl.load_workbook(p)
    for r in wb["Config"].iter_rows(min_col=2, max_col=3):
        if r[0].value and str(r[0].value).startswith("MAINTAIN/PUSH hoặc SCALE UP"):
            r[1].value = 5  # above the CUT threshold: makes no sense
    wb.save(p)
    lg = load_logic(p)
    assert ("ORDER", "camp_good") in _codes(lg)


def test_unreadable_file_falls_back_entirely(tmp_path):
    from factory import write_xlsx
    p = write_xlsx(tmp_path / "Alert_Logic_v9.xlsx", {"Sheet": [["x"]]})
    lg = load_logic(p)
    assert lg.params == DEFAULT_PARAMS and any(i["code"] == "NO_CONFIG" for i in lg.issues)

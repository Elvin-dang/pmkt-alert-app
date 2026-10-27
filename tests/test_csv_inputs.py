import shutil
from datetime import date

import pytest

from factory import make_all, make_all_csv
from pmkt_alert.loaders import InputError, detect_inputs, load_inputs
from pmkt_alert.logic import load_logic
from pmkt_alert.pipeline import result_to_json, run_rules


@pytest.fixture(scope="module")
def csv_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("csv")
    make_all_csv(d)
    return d


def test_detects_csv_tables(csv_dir):
    roles = detect_inputs([csv_dir])
    assert {k: v.name for k, v in roles.items()} == {
        "raw": "raw_sso_us.csv", "products": "Product Info.csv", "kpi": "KPI.csv", "ads": "ads_camp.csv",
        "activity": "Activity Log.csv", "defind": "Defind.csv", "logic": "Alert_Logic_Ver 1.xlsx"}


def test_csv_loads_same_as_xlsx(csv_dir, loaded):
    inp = load_inputs(detect_inputs([csv_dir]))
    assert len(inp.raw) == len(loaded.raw) and inp.raw["spend"].sum() == pytest.approx(loaded.raw["spend"].sum())
    assert inp.raw["date"].min() == date(2026, 9, 20)  # ISO dates with a BOM header
    assert sorted(inp.ads["date"].unique()) == sorted(loaded.ads["date"].unique())  # dd/mm/yyyy, semicolons
    assert set(inp.ads["campaign_id"]) == set(loaded.ads["campaign_id"])  # no '.0' on long ids
    assert len(inp.activity) == len(loaded.activity) and inp.activity["_row"].tolist() == [2, 3, 4, 5, 6]
    assert "Tên File" in inp.defind_text and inp.sources["raw"]["file"] == "raw_sso_us.csv"


def test_csv_results_match_xlsx(csv_dir, loaded, logic):
    a = result_to_json(run_rules(load_inputs(detect_inputs([csv_dir])), load_logic(csv_dir / "Alert_Logic_Ver 1.xlsx"), date(2026, 10, 19)))
    b = result_to_json(run_rules(loaded, logic, date(2026, 10, 19)))
    assert a["digest"] == b["digest"] and len(a["camp"]) == len(b["camp"])


def test_missing_csv_table_named(tmp_path):
    files = make_all_csv(tmp_path)
    files["kpi"].unlink()
    with pytest.raises(InputError, match="KPI"):
        detect_inputs([tmp_path])


def test_tracker_xlsx_with_ads_csv(tmp_path):
    x = make_all(tmp_path / "x")
    c = make_all_csv(tmp_path / "c")
    mix = tmp_path / "mix"
    mix.mkdir()
    for k in ("tracker", "activity", "logic", "defind"):
        shutil.copy(x[k], mix / x[k].name)
    shutil.copy(c["ads"], mix / "ads_camp.csv")
    roles = detect_inputs([mix])
    assert roles["tracker"].suffix == ".xlsx" and roles["ads"].suffix == ".csv"
    assert len(load_inputs(roles).ads) > 0

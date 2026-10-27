import shutil
from datetime import date

import pytest

from factory import FACTORY_YES4ALL_ROWS, make_all
from pmkt_alert.loaders import ROLES, InputError, detect_inputs, load_inputs


def test_detect_by_content_not_name(tmp_path):
    make_all(tmp_path, names={"ads": "whatever.xlsx"})
    roles = detect_inputs([tmp_path])
    assert roles["ads"].name == "whatever.xlsx" and set(roles) == set(ROLES)


def test_missing_role_message(tmp_path):
    files = make_all(tmp_path)
    files["ads"].unlink()
    with pytest.raises(InputError, match="ads_camp"):
        detect_inputs([tmp_path])


def test_duplicate_role_message(tmp_path):
    files = make_all(tmp_path)
    shutil.copy(files["tracker"], tmp_path / "copy.xlsx")
    with pytest.raises(InputError, match="copy.xlsx"):
        detect_inputs([tmp_path])


def test_ignores_lock_files(tmp_path):
    files = make_all(tmp_path)
    shutil.copy(files["ads"], tmp_path / "~$ads.xlsx")
    assert detect_inputs([tmp_path])["ads"].name == "ads.xlsx"


def test_ads_filtered_and_typed(loaded):
    assert set(loaded.ads["campaign_id"].map(type)) == {str}
    assert loaded.ads["spend"].dtype == float
    assert len(loaded.ads) == FACTORY_YES4ALL_ROWS  # factory's one BMe and one DSP row are dropped


def test_raw_spend_is_sp_sb_sd(loaded):
    row = loaded.raw.iloc[0]
    assert row["spend"] == 1.0 + 2.0 + 3.0  # sp=1, sb=2, sd=3, DSP_Spend=100 ignored
    assert row["date"] == date(2026, 9, 20)


def test_products_blank_pic_and_activity_columns(loaded):
    assert "" in set(loaded.products["PIC Oct"])
    assert list(loaded.activity.columns) == ["id", "level", "type", "action", "from_", "to", "time", "user"]
    assert len(loaded.activity) == 5


def test_event_days_and_defind(loaded):
    assert loaded.event_days[date(2026, 10, 2)] == "BAU" and loaded.event_days[date(2026, 10, 3)] == "FALL PRIME"
    assert "Tên File | Data | Sheet | Meaning" in loaded.defind_text
    assert loaded.kpi["month"].dtype.kind == "i"

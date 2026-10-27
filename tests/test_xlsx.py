import pandas as pd

from factory import break_dimension, write_xlsx
from pmkt_alert.xlsx import read_sheet, to_num


def test_reads_all_rows_despite_broken_dimension(tmp_path):
    p = write_xlsx(tmp_path / "log.xlsx", {"Activity Log": [["ID", "Level"]] + [[str(i), "x"] for i in range(500)]})
    break_dimension(p)
    df = read_sheet(p)
    assert len(df) == 500 and list(df.columns) == ["ID", "Level"]


def test_header_whitespace_stripped(tmp_path):
    p = write_xlsx(tmp_path / "a.xlsx", {"S": [["Last Time Ineligible (UTC) ", "b"], [1, 2]]})
    assert list(read_sheet(p, "S").columns) == ["Last Time Ineligible (UTC)", "b"]


def test_header_row_offset(tmp_path):
    p = write_xlsx(tmp_path / "a.xlsx", {"S": [["title"], [None], ["k", "v"], ["x", 1]]})
    assert read_sheet(p, "S", header_row=3).to_dict("records") == [{"k": "x", "v": 1}]


def test_to_num():
    s = pd.Series(["0E-10", "1,234.5", None, "", "#N/A", 3])
    assert to_num(s).tolist() == [0.0, 1234.5, 0.0, 0.0, 0.0, 3.0]

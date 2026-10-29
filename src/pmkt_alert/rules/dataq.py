"""Tier 0 – can the data be trusted before acting on it?"""
from dataclasses import dataclass

import pandas as pd


@dataclass
class Issue:
    code: str
    severity: str  # "WARN" | "INFO"
    title: str
    detail: str
    amount: float | None = None


def data_check(*, unmapped_rows: int, unmapped_spend: float, ads_spend_mtd: float, raw_spend_mtd: float,
               unmatched_camps: pd.DataFrame, duplicates: int, no_pic_pls: list[str], log_skipped: int,
               log_empty: bool, no_targets: bool = False, out_of_scope: int = 0, scope_label: str = "",
               in_scope: int | None = None, inv_none: bool = False, inv_stale=None, inv_missing: list | None = None) -> list[Issue]:
    out = []
    if inv_none:
        out.append(Issue("INV_NONE", "INFO", "Không có số liệu tồn kho (sheet Inventory AMZ)",
                         "Chưa áp chốt chặn tồn kho – PIC tự kiểm tra hàng trước khi tăng chi.", None))
    if inv_stale is not None:
        out.append(Issue("INV_STALE", "WARN", f"Số liệu tồn kho quá cũ (mới nhất {inv_stale:%d/%m/%Y})",
                         "Chưa áp chốt chặn tồn kho. Cập nhật sheet Inventory AMZ trong file Data rồi chạy lại.", None))
    if inv_missing:
        out.append(Issue("INV_MISSING", "WARN", f"{len(inv_missing)} ASIN đang bán chưa có số liệu tồn kho",
                         "Chưa áp chốt chặn cho các ASIN này: " + ", ".join(inv_missing[:10])
                         + (" …" if len(inv_missing) > 10 else ""), None))
    if in_scope == 0:
        out.append(Issue("NO_SCOPE", "WARN", f"Không có ASIN nào thuộc team '{scope_label}'",
                         "Kiểm tra 'Nhãn team được tracking' trong file logic và cột Team Label trong Product Info.", None))
    if out_of_scope:
        out.append(Issue("OUT_OF_SCOPE", "INFO", f"{out_of_scope} ASIN ngoài phạm vi team '{scope_label}'",
                         "Theo file logic, chỉ tính SKU có Team Label đúng nhãn team – các ASIN khác bị bỏ qua.", None))
    if no_targets:
        out.append(Issue("NO_TARGETS", "WARN", "KPI không có target cho tháng của as-of",
                         "Mọi PL sẽ là NO PLAN. Kiểm tra sheet KPI (Month) hoặc chọn as-of khác.", None))
    if unmapped_rows:
        out.append(Issue("UNMAPPED", "WARN", f"{unmapped_rows} dòng ads_camp chưa map được Product Line",
                         f"${unmapped_spend:,.2f} spend MTD không được tính vào alert campaign.", unmapped_spend))
    gap = ads_spend_mtd - raw_spend_mtd
    if raw_spend_mtd and abs(gap) > 0.03 * raw_spend_mtd:
        out.append(Issue("SPEND_GAP", "WARN", "Spend ads_camp lệch >3% so với raw_sso_us (MTD)",
                         f"ads_camp ${ads_spend_mtd:,.2f} vs raw ${raw_spend_mtd:,.2f} (lệch {gap / raw_spend_mtd:+.1%}). "
                         "Kiểm tra mapping PL / độ trễ data trước khi action.", gap))
    if len(unmatched_camps):
        top = unmatched_camps.sort_values("l7d_spend", ascending=False).head(5)
        total = float(unmatched_camps["l7d_spend"].sum())
        out.append(Issue("LOG_UNMATCHED", "INFO", f"{len(unmatched_camps)} campaign có spend chưa khớp tên với Activity Log",
                         "Các camp này luôn hiện là CHƯA ACTION. VD: " +
                         "; ".join(f"{c} (${s:,.2f})" for c, s in zip(top["campaign"], top["l7d_spend"])), total))
    if duplicates:
        out.append(Issue("DUP_ASIN", "INFO", f"{duplicates} ASIN trùng trong Product Info",
                         "Đã giữ dòng Active, rồi dòng đầu tiên.", None))
    if no_pic_pls:
        out.append(Issue("NO_PIC", "WARN", f"{len(no_pic_pls)} Product Line chưa có PIC",
                         "Nhóm vào 'Chưa có PIC': " + ", ".join(no_pic_pls[:10]), None))
    if log_skipped:
        out.append(Issue("LOG_SKIPPED", "INFO", f"{log_skipped} dòng Activity Log không đọc được thời gian", "", None))
    if log_empty:
        out.append(Issue("LOG_EMPTY", "WARN", "Activity Log trống",
                         "Không xác định được camp nào đã action → mọi alert đang là CHƯA ACTION.", None))
    return out

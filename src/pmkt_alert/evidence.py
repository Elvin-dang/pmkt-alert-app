"""Evidence for one result row: which file › sheet › columns › rows produced each number,
the formulas applied, and the Alert_Logic cells it was compared with."""
from datetime import date

import pandas as pd

from .aggregate import asin_map, pic_column
from .logic import Logic
from .rules.actions import parse_activity
from .windows import Windows

RAW_COLS = {"gmv": ["ordered_gmv_usd"], "ads_gmv": ["ppc_ordered_gmv_usd"], "spend": ["sp_spend", "sb_spend", "sd_spend"],
            "clicks": ["ppc_clicks"], "orders": ["ppc_orders"]}
ADS_COLS = {"spend": ["spend_usd"], "clicks": ["clicks"], "sales": ["sales_14d"], "orders": ["order_14d"]}
KPI_COLS = {"gmv": ["GMV"], "spend": ["Spend_final"]}
ROW_LIMIT = 20


def row_ranges(rows) -> str:
    nums = sorted({int(r) for r in rows if r == r and r is not None})
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i == len(nums) - 1 or nums[i + 1] != n + 1:
            out.append(str(start) if start == n else f"{start}–{n}")
            start = None
    return ", ".join(out)


def _clean(v):
    if isinstance(v, float):
        return None if v != v else round(v, 4)
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item"):
        return _clean(v.item())
    return v


def _columns_text(inputs, src: str, mapping: dict) -> str:
    letters = inputs.sources.get(src, {}).get("letters", {})
    parts = []
    for name, cols in mapping.items():
        refs = " + ".join(f"{c} ({letters[c]})" if c in letters else c for c in cols)
        parts.append(f"{name} = {refs}")
    return "; ".join(parts)


def _section(inputs, key: str, title: str, src: str, df: pd.DataFrame, filter_text: str, mapping: dict,
             show: list[str]) -> dict:
    meta = inputs.sources.get(src, {"file": "?", "sheet": src})
    rows_col = df["_row"] if "_row" in df.columns else []
    sample = df[[c for c in show + ["_row"] if c in df.columns]].head(ROW_LIMIT)
    return {
        "key": key, "title": title, "source": f"{meta['file']} › {meta['sheet']}" if meta.get("sheet") else meta["file"],
        "columns_text": _columns_text(inputs, src, mapping), "filter": filter_text, "row_count": int(len(df)),
        "row_ranges": row_ranges(rows_col),
        "rows": [{k: _clean(v) for k, v in r.items()} for r in sample.to_dict("records")],
        "totals": {c: float(df[c].sum()) for c in mapping if c in df.columns},
    }


def _between(df: pd.DataFrame, span) -> pd.DataFrame:
    return df[(df["date"] >= span[0]) & (df["date"] <= span[1])]


def _span(span) -> str:
    return f"{span[0]:%d/%m}–{span[1]:%d/%m/%Y}"


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1%}"


def _thresholds(logic: Logic, keys: list[str]) -> list[dict]:
    from .logic import ALL_LABELS, DISPLAY
    out = []
    for k in keys:
        if k in logic.params:
            label = DISPLAY.get(k, ALL_LABELS[k][1])
            if k in ("trend_spend", "trend_acos", "trend_tacos"):
                label = f"Ngưỡng thay đổi {label} L7D vs P7D (±)"
            out.append({"key": k, "label": label, "cell": logic.cells.get(k, "Config"),
                        "value": logic.params[k], "file": logic.path.name})
        elif k in logic.k_by_type:
            out.append({"key": k, "label": f"k (order kỳ vọng) cho {k}", "cell": logic.cells.get(k, "Config"),
                        "value": logic.k_by_type[k], "file": logic.path.name})
    return out


def _pl_evidence(inputs, logic: Logic, rj: dict, win: Windows, amap: pd.DataFrame, pl: str, level: str = "pl") -> dict:
    """Evidence for a Product Line, or (score model) for a whole PIC when level == 'pic'."""
    rows = rj["pl"] if level == "pl" else rj.get("pics", [])
    row = next((r for r in rows if r.get(level) == pl), None)
    if row is None:
        raise ValueError(f"Không có {'Product Line' if level == 'pl' else 'PIC'} '{pl}' trong lần chạy này")
    asins = set(amap.loc[amap[level] == pl, "asin"])
    pic_col = "PMKT PIC_Final" if rj.get("model") == "score_v3" else pic_column(list(inputs.products.columns), win.as_of)
    raw = inputs.raw[inputs.raw["asin"].isin(asins)]
    ads = inputs.ads[inputs.ads["asin"].isin(asins)]
    kpi = inputs.kpi[(inputs.kpi["asin"].isin(asins)) & (inputs.kpi["month"] == win.as_of.month)]
    prods = inputs.products[inputs.products["asin"].isin(asins)]
    asin_txt = (f"{len(asins)} ASIN của PL (product_line_old = '{pl}')" if level == "pl"
                else f"{len(asins)} ASIN của PIC '{pl}'")
    if rj.get("model") == "score_v3" and logic.texts.get("team_label"):
        asin_txt += f" · chỉ Team Label = '{logic.texts['team_label']}'"
    map_filter = (f"product_line_old = '{pl}'" if level == "pl" else f"{pic_col} = '{pl}'") + f" · PIC lấy từ cột {pic_col}"
    raw_show = ["date", "asin", "sku", "gmv", "ads_gmv", "spend"]
    sections = [
        _section(inputs, "mapping", "Mapping ASIN → PL → PIC", "products", prods, map_filter,
                 {}, ["asin", "sku", "pl", pic_col, "status"]),
        _section(inputs, "kpi", f"Target tháng {win.as_of.month}", "kpi", kpi, f"Month = {win.as_of.month} · {asin_txt}",
                 KPI_COLS, ["month", "asin", "gmv", "spend"]),
        _section(inputs, "raw_mtd", f"Thực tế MTD ({_span(win.mtd)})", "raw", _between(raw, win.mtd), f"report_date {_span(win.mtd)} · {asin_txt}",
                 RAW_COLS, raw_show),
        _section(inputs, "raw_l7d", f"L7D ({_span(win.l7d)})", "raw", _between(raw, win.l7d), f"report_date {_span(win.l7d)} · {asin_txt}",
                 RAW_COLS, raw_show),
        _section(inputs, "raw_p7d", f"P7D ({_span(win.p7d)})", "raw", _between(raw, win.p7d), f"report_date {_span(win.p7d)} · {asin_txt}",
                 RAW_COLS, raw_show),
        _section(inputs, "ads_l7d", "ACoS/CR chuẩn của PL (ads_camp L7D)", "ads", _between(ads, win.l7d),
                 f"report_date {_span(win.l7d)} · mọi campaign có ASIN của PL", ADS_COLS,
                 ["date", "campaign_id", "asin", "spend", "clicks", "sales", "orders"]),
    ]
    g = lambda k: row.get(k)  # noqa: E731
    if logic.model == "score_v3":
        return _pl_score_evidence(logic, rj, win, row, pl, sections)
    calc = [
        {"label": "%GMV vs target", "formula": f"{g('gmv_mtd'):,.2f} ÷ {g('target_gmv'):,.2f}", "value": _pct(g("pct_gmv"))},
        {"label": "%Spend vs target", "formula": f"{g('spend_mtd'):,.2f} ÷ {g('target_spend'):,.2f}", "value": _pct(g("pct_spend"))},
        {"label": "GMV pace", "formula": f"{_pct(g('pct_gmv'))} ÷ time gone {win.time_gone:.1%}", "value": f"{g('gmv_pace'):.2f}"},
        {"label": "Spend pace", "formula": f"{_pct(g('pct_spend'))} ÷ time gone {win.time_gone:.1%}", "value": f"{g('spend_pace'):.2f}"},
        {"label": "TACoS ÷ target", "formula": f"{_pct(g('actual_tacos'))} ÷ {_pct(g('target_tacos'))}", "value": f"{g('tacos_ratio'):.2f}"},
        {"label": "Pacing", "formula": "Thứ tự rule: NO PLAN → KHÔNG CHẠY → SCALE DOWN → OPTIMIZE → SCALE UP → BUDGET CAP → CHECK → MAINTAIN",
         "value": f"{g('pacing_action')} ({g('pacing_sev')})"},
        {"label": "Δ Spend / Δ ACoS / Δ TACoS (L7D vs P7D)", "formula": f"key {g('trend_key')} tra Matrix_PL",
         "value": " / ".join("—" if g(k) is None else f"{g(k):+.0%}" for k in ("d_spend", "d_acos", "d_tacos"))
         + (f" → {g('trend_label')}" if g("trend_label") else " → (không nhãn)")},
    ]
    thresholds = _thresholds(logic, ["gmv_pace_low", "spend_pace_low", "spend_pace_high", "tacos_over", "not_running",
                                     "budget_cap", "trend_spend", "trend_acos", "trend_tacos", "trend_min_spend"])
    mkey = f"matrix:{g('trend_key')}"
    if mkey in logic.cells:
        thresholds.append({"key": "matrix", "label": f"Matrix_PL {g('trend_key')}", "cell": logic.cells[mkey],
                           "value": logic.matrix[g("trend_key")][0] or "(trống)", "file": logic.path.name})
    return {"unit_id": row["unit_id"], "title": f"{pl} · {g('pacing_action')}", "sections": sections, "calc": calc,
            "thresholds": thresholds}


def _pl_score_evidence(logic: Logic, rj: dict, win: Windows, row: dict, pl: str, sections: list) -> dict:
    p, d, g = logic.params, rj.get("dept") or {}, row.get
    sens = {"s1": ("TACoS ÷ target riêng − 1", "sens_tacos", "w1"), "s2": ("TACoS ÷ target Dept − 1", "sens_tacos", "w2"),
            "s3": ("−(Ads dependency ÷ benchmark − 1)", "sens_ads", "w3"), "s4": ("Δ TACoS L7D vs P7D", "sens_trend", "w4"),
            "s5": ("GMV pace − 1", "sens_gmv", "w5"), "s6": ("Spend pace − 1", "sens_spend", "w6")}
    calc = [
        {"label": "TACoS MTD", "formula": f"{g('spend_mtd'):,.2f} ÷ {g('gmv_mtd'):,.2f}", "value": _pct(g("actual_tacos"))},
        {"label": "Target TACoS riêng / Dept", "formula": "target spend ÷ target GMV", "value": f"{_pct(g('target_tacos'))} / {_pct(d.get('target_tacos'))}"},
        {"label": "Ads dependency", "formula": f"Ads GMV ÷ GMV · benchmark Dept {_pct(d.get('benchmark'))}", "value": _pct(g("ads_dep"))},
        {"label": "GMV pace / Spend pace", "formula": f"% so target ÷ time gone {win.time_gone:.1%}", "value": f"{g('gmv_pace'):.2f} / {g('spend_pace'):.2f}"},
        *[{"label": f"{k} (×{p[w]:g})", "formula": f"({desc}) ÷ {p[s]:g} × 100, giới hạn ±100", "value": f"{g(k):+.1f}"}
          for k, (desc, s, w) in sens.items()],
        {"label": "SCORE", "formula": "Σ(w × s) ÷ Σw", "value": "—" if g("score") is None else f"{g('score'):+.1f}"},
        {"label": "Excess$ vs Dept", "formula": f"{g('spend_mtd'):,.2f} − {_pct(d.get('target_tacos'))} × {g('gmv_mtd'):,.2f}", "value": f"${g('excess_dept'):,.2f}"},
        {"label": "Department", "formula": f"coverage {_pct(d.get('coverage'))} · ngưỡng SCALE DOWN đang áp dụng {d.get('sd_threshold')}",
         "value": d.get("regime", "—")},
        {"label": "Action", "formula": "NO DATA → NO PLAN → KHÔNG CHẠY → CHƯA ĐỦ DATA → điểm (chốt chặn Excess$ vs Dept) → BUDGET CAP",
         "value": f"{g('pacing_action')} ({g('pacing_sev') or 'không mức'})"},
        {"label": "Trend L7D vs P7D", "formula": f"key {g('trend_key')} tra Matrix_PL", "value": g("trend_label") or "(không nhãn)"},
    ]
    keys = [f"w{i}" for i in range(1, 7)] + ["sens_tacos", "sens_ads", "sens_trend", "sens_gmv", "sens_spend", "score_sd",
                                             "score_opt", "score_up", "sd_room", "sd_over", "min_time_gone", "min_spend",
                                             "not_running", "budget_cap", "trend_spend", "trend_acos", "trend_tacos",
                                             "trend_min_spend"]
    thresholds = _thresholds(logic, keys)
    if logic.texts.get("team_label"):
        thresholds.insert(0, {"key": "team_label", "label": "Phạm vi: Team Label", "cell": logic.cells.get("team_label", "Config"),
                              "value": logic.texts["team_label"], "file": logic.path.name})
    return {"unit_id": row["unit_id"], "title": f"{pl} · {g('pacing_action')} (score {g('score') or 0:+.0f})",
            "sections": sections, "calc": calc, "thresholds": thresholds}


def _camp_evidence(inputs, logic: Logic, rj: dict, win: Windows, amap: pd.DataFrame, unit_id: str) -> dict:
    row = next((r for r in rj["camp"] if r["unit_id"] == unit_id), None)
    if row is None:
        raise ValueError(f"Không có campaign '{unit_id}' trong lần chạy này")
    cid, pl = row["campaign_id"], row["pl"]
    asins = set(amap.loc[amap["pl"] == pl, "asin"])
    ads = inputs.ads[(inputs.ads["campaign_id"] == cid) & (inputs.ads["asin"].isin(asins))]
    base = inputs.ads[inputs.ads["asin"].isin(asins)]
    show = ["date", "campaign_id", "asin", "spend", "clicks", "sales", "orders"]
    filt = f"campaign_id = {cid} · ASIN thuộc PL '{pl}'"
    acts = parse_activity(inputs.activity)
    acts = acts[(acts["camp_key"] == row.get("camp_key")) & (acts["action_date"] <= win.as_of)]
    sections = [
        _section(inputs, "ads_l7d", f"Campaign L7D ({_span(win.l7d)})", "ads", _between(ads, win.l7d), filt, ADS_COLS, show),
        _section(inputs, "ads_p7d", f"Campaign P7D ({_span(win.p7d)})", "ads", _between(ads, win.p7d), filt, ADS_COLS, show),
        _section(inputs, "ads_l3d", f"Campaign L3D ({_span(win.l3d)})", "ads", _between(ads, win.l3d), filt, ADS_COLS, show),
        _section(inputs, "ads_pl_l7d", "ACoS/CR chuẩn của PL (ads_camp L7D)", "ads", _between(base, win.l7d),
                 f"mọi campaign có ASIN của PL '{pl}'", ADS_COLS, show),
        {**_section(inputs, "activity", "Activity Log (khớp theo tên campaign)", "activity", acts,
                    f"campaign = '{row.get('campaign')}' (tên đã chuẩn hoá, bỏ hậu tố _ID) · ngày ≤ {win.as_of:%d/%m}", {},
                    ["action_date", "category", "user"])},
    ]
    g = lambda k: row.get(k)  # noqa: E731
    calc = [
        {"label": "ACoS L7D camp", "formula": f"{g('l7d_spend'):,.2f} ÷ {g('l7d_sales'):,.2f}", "value": _pct(g("l7d_acos"))},
        {"label": "ACoS L7D của PL", "formula": "spend ÷ sales của mọi campaign trong PL (L7D)", "value": _pct(g("pl_acos"))},
        {"label": "ACoS camp ÷ ACoS PL", "formula": f"{_pct(g('l7d_acos'))} ÷ {_pct(g('pl_acos'))}",
         "value": "—" if g("acos_ratio") is None else f"{g('acos_ratio'):.2f}×"},
        {"label": "Min clicks", "formula": f"MAX(sàn, ROUNDUP(k ÷ CR PL {_pct(g('pl_cr'))}))", "value": f"{g('min_clicks')} (có {g('l7d_clicks'):.0f})"},
        {"label": "Excess spend", "formula": f"MAX(0, {g('l7d_spend'):,.2f} − {g('l7d_sales'):,.2f} × {_pct(g('pl_acos'))})",
         "value": f"${g('excess'):,.2f}"},
        {"label": "Action", "formula": f"PL đang {g('pl_action')}", "value": f"{g('base_action')} ({g('sev') or 'không mức'})"},
        {"label": "Trạng thái action", "formula": "Activity Log trong cửa sổ L3D", "value": g("final_label") or "—"},
    ]
    thresholds = _thresholds(logic, ["camp_cut", "camp_good", "camp_optimize", "min_clicks", "excess_high", g("type"),
                                     "trend_acos", "action_window", "followup_days", "improving_ratio"])
    return {"unit_id": unit_id, "title": f"{g('campaign')} · {g('base_action')}", "sections": sections, "calc": calc,
            "thresholds": thresholds}


def evidence(inputs, logic: Logic, rj: dict, unit_id: str) -> dict:  # noqa: C901
    win = Windows(date.fromisoformat(rj["as_of"]))
    if rj.get("model") == "score_v3":
        amap = asin_map(inputs.products, win.as_of, pic_col="PMKT PIC_Final")
        label = logic.texts.get("team_label")
        if label and "team" in amap.columns:
            amap = amap[amap["team"] == label]
    else:
        amap = asin_map(inputs.products, win.as_of)
    if unit_id.startswith("pl:"):
        return _pl_evidence(inputs, logic, rj, win, amap, unit_id[3:])
    if unit_id.startswith("pic:"):
        return _pl_evidence(inputs, logic, rj, win, amap, unit_id[4:], level="pic")
    if unit_id.startswith("camp:"):
        return _camp_evidence(inputs, logic, rj, win, amap, unit_id)
    raise ValueError(f"Không có bằng chứng cho '{unit_id}'")

from pathlib import Path

import pandas as pd

PL_COLS = {"pl": "Product Line", "pacing_sev": "Mức", "pacing_action": "Pacing", "trend_label": "Trend L7D",
           "pct_gmv": "%GMV", "pct_spend": "%Spend", "actual_tacos": "TACoS", "target_tacos": "Target TACoS",
           "d_spend": "Δ Spend", "pacing_reason": "Lý do", "trend_action": "Gợi ý trend"}
CAMP_COLS = {"pl": "Product Line", "campaign": "Campaign", "campaign_id": "Campaign ID", "sev": "Mức",
             "final_label": "Hành động", "status": "Trạng thái", "l7d_spend": "L7D Spend", "l7d_acos": "L7D ACoS",
             "pl_acos": "PL ACoS", "acos_ratio": "ACoS ÷ PL", "excess": "Excess $", "camp_trend": "Trend",
             "followup_check": "Follow-up"}


def export_pic(result_json: dict, ai_json: dict | None, pic: str, path: Path) -> Path:
    path = Path(path)
    pl = pd.DataFrame([r for r in result_json["pl"] if r["pic"] == pic], columns=list(PL_COLS)).rename(columns=PL_COLS)
    camp = pd.DataFrame([r for r in result_json["camp"] if r["pic"] == pic and r["sev"] in ("HIGH", "MED")],
                        columns=list(CAMP_COLS)).rename(columns=CAMP_COLS)
    mine = ((ai_json or {}).get("per_pic") or {}).get(pic, {})
    todos = pd.DataFrame(mine.get("todos", []), columns=["severity", "due", "title", "detail"])
    insights = pd.DataFrame([{"Insight": i["text"]} for i in mine.get("insights", [])], columns=["Insight"])
    data = pd.DataFrame(result_json.get("issues", []), columns=["severity", "title", "detail"])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in [("Cảnh báo PL", pl), ("Cảnh báo Campaign", camp), ("To-do", todos), ("Insight", insights), ("Data", data)]:
            df.to_excel(xw, sheet_name=name, index=False)
    return path

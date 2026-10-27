"""Prompt builders and output schemas for Claude Code. Every prompt demands JSON only,
Vietnamese text, numbers copied from the given rows, and unit_id citations."""
import json

from .logic import PARAM_LABELS, Logic

_STR_LIST = {"type": "array", "items": {"type": "string"}}
INSIGHTS_SCHEMA = {
    "type": "object", "required": ["insights", "todos"],
    "properties": {
        "insights": {"type": "array", "items": {"type": "object", "required": ["text", "refs"],
                                                 "properties": {"text": {"type": "string"}, "refs": _STR_LIST}}},
        "todos": {"type": "array", "items": {"type": "object", "required": ["title", "detail", "severity", "due", "refs"],
                                              "properties": {"title": {"type": "string"}, "detail": {"type": "string"},
                                                             "severity": {"enum": ["HIGH", "MED"]},
                                                             "due": {"enum": ["today", "week"]}, "refs": _STR_LIST}}},
        "slack": {"type": "string"},
    },
}
REVIEW_SCHEMA = {
    "type": "object", "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": {
        "type": "object", "required": ["severity", "title", "detail", "kind"],
        "properties": {"severity": {"enum": ["HIGH", "MED", "INFO"]}, "title": {"type": "string"},
                       "detail": {"type": "string"}, "kind": {"enum": ["param", "rule"]},
                       "param_key": {"type": ["string", "null"]}, "proposed_value": {"type": ["number", "string", "null"]}}}}},
}
FEEDBACK_SCHEMA = {
    "type": "object", "required": ["kind", "rationale"],
    "properties": {"kind": {"enum": ["param", "rule", "lesson"]}, "param_key": {"type": ["string", "null"]},
                   "proposed_value": {"type": ["number", "string", "null"]}, "rationale": {"type": "string"},
                   "lesson_text": {"type": ["string", "null"]}},
}
STYLE_SCHEMA = {"type": "object", "required": ["slack"], "properties": {"slack": {"type": "string"}}}

PL_FIELDS = ["unit_id", "pl", "pacing_action", "pacing_sev", "pacing_reason", "target_gmv", "target_spend", "gmv_mtd",
             "spend_mtd", "pct_gmv", "pct_spend", "actual_tacos", "target_tacos", "trend_label", "trend_action",
             "l7d_spend", "d_spend", "d_acos", "d_tacos"]
CAMP_FIELDS = ["unit_id", "campaign", "pl", "type", "base_action", "sev", "status", "final_label", "followup_check",
               "l7d_spend", "l7d_sales", "l7d_clicks", "l7d_orders", "l7d_acos", "pl_acos", "acos_ratio", "excess",
               "d_spend", "d_acos", "camp_trend"]

_STYLE_TEXT = {
    "language": {"vi_en_terms": "Tiếng Việt, giữ thuật ngữ tiếng Anh (ACoS, TACoS, bid, budget, PL, PIC)",
                 "vi": "Tiếng Việt hoàn toàn", "en": "English"},
    "pronoun": {"em_anhchi": "xưng em, gọi anh/chị", "minh_ban": "xưng mình, gọi bạn", "none": "không xưng hô"},
    "length": {"short": "ngắn gọn, gạch đầu dòng", "medium": "vừa phải", "long": "chi tiết"},
    "tone": {"friendly_direct": "thân thiện, thẳng vào việc", "formal": "trang trọng", "chat": "rất ngắn, kiểu chat"},
    "emoji": {"none": "không dùng emoji", "low": "ít emoji, chỉ :rotating_light: cho HIGH", "free": "dùng emoji thoải mái"},
}

_RULES = """QUY TẮC BẮT BUỘC:
- Chỉ trả về MỘT object JSON đúng schema bên dưới, không thêm chữ nào khác.
- Mọi con số bạn viết phải lấy NGUYÊN từ các dòng dữ liệu được cung cấp (có thể làm tròn hoặc đổi tỉ lệ sang %). Không tự tính số mới.
- Mỗi insight/to-do phải ghi `refs` = danh sách unit_id của các dòng bạn dựa vào.
- Không bịa thông tin không có trong dữ liệu."""


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def style_text(style: dict) -> str:
    parts = [_STYLE_TEXT[k].get(style.get(k), str(style.get(k))) for k in _STYLE_TEXT]
    out = "Văn phong: " + "; ".join(parts) + "."
    if style.get("rules"):
        out += f"\nLưu ý thêm của người dùng: {style['rules']}"
    if style.get("samples"):
        out += "\nTin nhắn mẫu của người dùng (bắt chước giọng văn, không chép nội dung):\n" + \
               "\n---\n".join(style["samples"][-5:])
    return out


def params_text(logic: Logic) -> str:
    lines = [f"- {k} = {logic.params[k]} ({PARAM_LABELS[k][1]})" for k in PARAM_LABELS]
    lines += [f"- matrix:{k} = {v[0] or '(trống)'}" for k, v in sorted(logic.matrix.items())]
    return "\n".join(lines)


def insights_prompt(pic: str, rows: dict, digest_row: dict, logic: Logic, lessons: list[str], style: dict,
                    defind_text: str, ineligible: list[dict]) -> str:
    return f"""Bạn là chuyên gia Performance Marketing Amazon, viết báo cáo hằng ngày cho PIC "{pic}".
Dữ liệu dưới đây đã được hệ thống rule tính sẵn (Alert_Logic Ver {logic.version}).

{_RULES}

{style_text(style)}

Bài học đã được duyệt (luôn tuân theo):
{chr(10).join('- ' + x for x in lessons) or '- (chưa có)'}

Từ điển data:
{defind_text}

Logic các tầng:
{logic.tiers_text}

Tổng quan PIC (digest): {_j(digest_row)}
Product Line cần chú ý: {_j(rows['pl'])}
Campaign cần chú ý: {_j(rows['camp'])}
ASIN đang INELIGIBLE (L7D): {_j(ineligible)}

Hãy viết:
- insights: 2–5 nhận định "vì sao" (nguyên nhân, bối cảnh), mỗi cái 1–2 câu.
- todos: tối đa 8 việc cụ thể, ưu tiên HIGH và excess spend lớn; due = "today" cho HIGH, "week" cho MED.
- slack: một tin nhắn Slack gửi PIC theo văn phong trên, tóm tắt việc HIGH hôm nay và tổng excess spend.

Schema: {_j(INSIGHTS_SCHEMA)}"""


def review_prompt(result_json: dict, logic: Logic, event_days: dict, feedback: list[dict]) -> str:
    from collections import Counter
    pl, camp = result_json["pl"], result_json["camp"]
    dist = {
        "so_pl": len(pl), "so_campaign": len(camp),
        "pacing_action": Counter(r["pacing_action"] for r in pl), "pacing_sev": Counter(r["pacing_sev"] for r in pl),
        "trend_label": Counter(r["trend_label"] or "(trống)" for r in pl),
        "base_action": Counter(r["base_action"] for r in camp), "camp_sev": Counter(r["sev"] or "(trống)" for r in camp),
        "status": Counter(r["status"] or "(trống)" for r in camp),
        "no_plan_spend_mtd_top": sorted(([r["pl"], r["spend_mtd"]] for r in pl if str(r["pacing_action"]).startswith("NO PLAN")),
                                        key=lambda x: -x[1])[:5],
        "data_issues": [i["title"] for i in result_json.get("issues", [])],
    }
    events = {str(k): v for k, v in event_days.items()}
    return f"""Bạn là người rà soát logic alert cho team Performance Marketing Amazon. As-of {result_json['as_of']}.
Nhiệm vụ: tìm lỗ hổng của LOGIC (không phải của PIC) dựa trên phân bố kết quả lần chạy này và góp ý gần đây.
Ví dụ lỗ hổng: ngưỡng bắt quá nhiều/quá ít, nhãn không phân biệt mức độ, so sánh L7D vs P7D bị méo do ngày event.

Chỉ trả về MỘT object JSON đúng schema. Văn phong trung tính, chính xác, tiếng Việt.
- kind = "param" khi chỉ cần đổi một tham số có sẵn; khi đó param_key PHẢI là một key trong danh sách bên dưới và proposed_value là giá trị mới.
- Nếu một phát hiện có thể giảm bớt bằng cách chỉnh tham số có sẵn (kể cả chưa giải quyết triệt để), ưu tiên kind = "param" để người dùng backtest được.
- kind = "rule" khi cần thêm/sửa cấu trúc rule.
- Tối đa 6 phát hiện, quan trọng nhất trước.

Tham số hiện tại:
{params_text(logic)}

Logic các tầng:
{logic.tiers_text}

Phân bố kết quả: {_j(dist)}
Lịch event (ngày → nhãn): {_j(events)}
Góp ý gần đây của người dùng: {_j(feedback[-20:])}

Schema: {_j(REVIEW_SCHEMA)}"""


def feedback_prompt(item: dict, row: dict, logic: Logic, lessons: list[str]) -> str:
    return f"""Người dùng đánh dấu một dòng output của hệ thống alert là "chưa hợp lý".
So góp ý với logic hiện tại và chọn MỘT hướng xử lý:
- "param": đổi một tham số có sẵn sẽ sửa được (param_key phải nằm trong danh sách, kèm proposed_value).
- "rule": cần thêm/sửa cấu trúc rule (mô tả trong rationale).
- "lesson": không cần đổi logic, chỉ cần nhớ một bài học khi viết insight/to-do (lesson_text ngắn, 1 câu).

Chỉ trả về MỘT object JSON đúng schema, tiếng Việt.

Góp ý: {_j(item)}
Dòng output: {_j(row)}
Tham số hiện tại:
{params_text(logic)}
Logic các tầng:
{logic.tiers_text}
Bài học hiện có: {_j(lessons)}

Schema: {_j(FEEDBACK_SCHEMA)}"""


def style_prompt(style: dict, digest_row: dict, rows: dict) -> str:
    return f"""Viết MỘT tin nhắn Slack gửi PIC "{digest_row.get('pic')}" tóm tắt việc cần làm hôm nay.
{_RULES}

{style_text(style)}

Tổng quan: {_j(digest_row)}
Dữ liệu: {_j(rows)}

Schema: {_j(STYLE_SCHEMA)}"""

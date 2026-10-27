"""Per-run Claude orchestration: one call per PIC (insights, to-dos, Slack) plus one logic review.
Any failure leaves the rule results intact; ungrounded text is dropped."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .claude import ClaudeError, ask, filter_grounded, grounded
from .logic import Logic, valid_change
from .prompts import CAMP_FIELDS, INSIGHTS_SCHEMA, PL_FIELDS, REVIEW_SCHEMA, insights_prompt, review_prompt
from .store import Store
from .windows import Windows

SEV_RANK = {"HIGH": 0, "MED": 1}


def fallback_slack(d: dict, as_of: str) -> str:
    day = date.fromisoformat(as_of)
    return (f"Chào {d['pic']}, báo cáo ngày {day:%d/%m} (L7D): {d['pl_high']} PL HIGH, {d['pl_med']} PL MED, "
            f"{d['pl_trend_review']} PL có trend cần review; {d['camp_high'] + d['camp_med']} campaign cần action mới "
            f"(dư chi ~${d['excess_new']:,.0f}), {d['camp_followup']} campaign đã action đang follow-up.")


def pic_rows(result_json: dict, pic: str) -> dict:
    pl = [r for r in result_json["pl"] if r["pic"] == pic]
    camp = [r for r in result_json["camp"] if r["pic"] == pic]
    score = {"HIGH": 3e6, "MED": 2e6}
    pl_top = sorted(pl, key=lambda r: -(score.get(r["pacing_sev"], 0) + (1e6 if str(r["trend_label"]).startswith("REVIEW") else 0)
                                       + (r["spend_mtd"] or 0)))[:15]
    camp_top = sorted((r for r in camp if r["sev"] in SEV_RANK), key=lambda r: (SEV_RANK[r["sev"]], -(r["excess"] or 0)))[:25]
    return {"pl": [{k: r.get(k) for k in PL_FIELDS} for r in pl_top],
            "camp": [{k: r.get(k) for k in CAMP_FIELDS} for r in camp_top],
            "all": {r["unit_id"]: r for r in pl + camp}}


def _ask_twice(ask_fn, prompt: str, schema: dict) -> dict:
    try:
        return ask_fn(prompt, schema)
    except ClaudeError:
        return ask_fn(prompt, schema)


def generate(result_json: dict, logic: Logic, store: Store, event_days: dict, defind_text: str,
             ineligible: list[dict] | None = None, ask_fn=ask) -> dict:
    lessons = [x["text"] for x in store.lessons()]
    style = store.get_style()
    context = {"time_gone": Windows(date.fromisoformat(result_json["as_of"])).time_gone}
    errors: list[str] = []

    def one_pic(d: dict) -> tuple[str, dict]:
        pic = d["pic"]
        rows = pic_rows(result_json, pic)
        implicit = [d, context]
        fallback = fallback_slack(d, result_json["as_of"])
        if not any(d[k] for k in ("pl_high", "pl_med", "pl_trend_review", "camp_high", "camp_med", "camp_followup")):
            return pic, {"insights": [], "todos": [], "slack": fallback, "dropped": 0}
        inel = [x for x in (ineligible or []) if x.get("pic") == pic]
        prompt = insights_prompt(pic, rows, d, logic, lessons, style, defind_text, inel)
        try:
            out = _ask_twice(ask_fn, prompt, INSIGHTS_SCHEMA)
        except ClaudeError as e:
            errors.append(str(e))
            return pic, {"insights": [], "todos": [], "slack": fallback, "dropped": 0, "error": str(e)}
        out.setdefault("slack", "")
        ins, ins_drop = filter_grounded(out["insights"], rows["all"], ("text",), implicit)
        todos, todo_drop = filter_grounded(out["todos"], rows["all"], ("title", "detail"), implicit)
        slack_ok = grounded(out["slack"], list(rows["all"].values()) + implicit)
        return pic, {"insights": ins, "todos": todos, "slack": out["slack"] if slack_ok and out["slack"] else fallback,
                     "dropped": len(ins_drop) + len(todo_drop) + (0 if slack_ok else 1)}

    def review() -> list[dict]:
        try:
            out = _ask_twice(ask_fn, review_prompt(result_json, logic, event_days, store.list_feedback()), REVIEW_SCHEMA)
        except ClaudeError as e:
            errors.append(str(e))
            return []
        findings = out["findings"]
        for f in findings:
            if f["kind"] == "param" and not valid_change(f.get("param_key") or "", f.get("proposed_value"), logic):
                f["kind"] = "rule"
        return findings

    with ThreadPoolExecutor(max_workers=4) as pool:
        review_future = pool.submit(review)
        per_pic = dict(pool.map(one_pic, result_json["digest"]))
        findings = review_future.result()
    return {"claude_ok": not errors, "error": errors[0] if errors else None, "per_pic": per_pic, "review": findings}

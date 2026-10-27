"""Per-run Claude orchestration, per PIC:
1. facts – rule rows + comparisons (previous run, team average)    [code]
2. draft – insights, to-dos, message                               [Claude]
3. check – numbers grounded, refs exist, advice agrees with the rule label   [code]
4. critic – rewrite for clarity: no contradictions, duplicates, jargon        [Claude, careful mode]
5. check again – anything failing falls back to the checked draft             [code]
Plus one logic review. Any failure leaves the rule results intact."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .claude import ClaudeError, ask, filter_grounded, grounded
from .logic import Logic, valid_change
from .prompts import (CAMP_FIELDS, INSIGHTS_SCHEMA, PL_FIELDS, REVIEW_SCHEMA, critic_prompt, insights_prompt,
                      review_prompt)
from .scorecard import scorecard
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


# Advice that contradicts the rule's direction for the row it cites is dropped.
_DOWN = ("SCALE DOWN", "OPTIMIZE", "CUT", "PAUSE")
_UP = ("SCALE UP", "MAINTAIN/PUSH")
_FORBID = {
    "down": ("tăng bid", "tăng budget", "scale up", "đẩy mạnh", "đẩy thêm", "push", "mở rộng budget"),
    "up": ("scale down", "cắt", "pause", "tắt", "giảm bid", "giảm budget", "negate"),
}


def _direction(row: dict) -> str | None:
    action = str(row.get("base_action") or row.get("pacing_action") or "")
    if action.startswith(_DOWN):
        return "down"
    if action.startswith(_UP):
        return "up"
    return None


_NEGATION = ("đừng", "không", "chưa", "tránh", "ngừng", "dừng", "thay vì", "không nên")


def consistent(text: str, rows: list[dict]) -> bool:
    dirs = {_direction(r) for r in rows}
    if len(dirs) != 1 or None in dirs:
        return True  # no single direction to judge against
    low = text.lower()
    for w in _FORBID[dirs.pop()]:
        start = low.find(w)
        while start != -1:
            if not any(n in low[max(0, start - 12):start] for n in _NEGATION):  # "đừng tăng bid" is fine
                return False
            start = low.find(w, start + 1)
    return True


def _verify(out: dict, rows_all: dict, implicit: list[dict]) -> dict:
    """Step 3/5: keep only items whose numbers are grounded, refs exist and advice agrees with the rule."""
    ins, ins_drop = filter_grounded(out.get("insights", []), rows_all, ("text",), implicit)
    todos, todo_drop = filter_grounded(out.get("todos", []), rows_all, ("title", "detail"), implicit)
    agree = lambda it, keys: consistent(" ".join(str(it.get(k, "")) for k in keys), [rows_all[r] for r in it.get("refs", [])])  # noqa: E731
    ins_ok = [i for i in ins if agree(i, ("text",))]
    todos_ok = [t for t in todos if agree(t, ("title", "detail"))]
    slack = out.get("slack") or ""
    slack_ok = bool(slack) and grounded(slack, list(rows_all.values()) + implicit)
    return {"insights": ins_ok, "todos": todos_ok, "slack": slack if slack_ok else "",
            "dropped": len(ins_drop) + len(todo_drop) + len(ins) - len(ins_ok) + len(todos) - len(todos_ok)
            + (0 if slack_ok or not slack else 1),
            "all_ok": not ins_drop and not todo_drop and len(ins_ok) == len(ins) and len(todos_ok) == len(todos)}


def _comparisons(result_json: dict, store: Store) -> dict:
    """Step 1 context: the PIC's previous run and the team average, so Claude can say 'better/worse than'."""
    prev = None
    for r in store.list_runs():
        if r["as_of"] and r["as_of"] < result_json["as_of"]:
            prev = store.load_run(r["run_id"]).get("result")
            break
    sc = scorecard(result_json)
    keys = ("gmv_pace", "tacos_ratio", "acos_l7d", "excess_share")
    ranked = [p for p in sc["pics"] if p["rank"]]
    avg = {k: round(sum(p["values"][k] for p in ranked if p["values"][k] is not None)
                    / max(1, sum(1 for p in ranked if p["values"][k] is not None)), 4) for k in keys}
    out = {}
    for p in sc["pics"]:
        prev_d = next((d for d in (prev or {}).get("digest", []) if d["pic"] == p["pic"]), None)
        out[p["pic"]] = {"previous": {"as_of": prev["as_of"], "digest": prev_d} if prev_d else None, "team_avg": avg,
                         "this_pic": {k: p["values"][k] for k in keys}}
    return out


def _ask_twice(ask_fn, prompt: str, schema: dict) -> dict:
    try:
        return ask_fn(prompt, schema)
    except ClaudeError as e:
        if not e.retryable:
            raise
        return ask_fn(prompt, schema)


def offline(result_json: dict, reason: str) -> dict:
    """AI section when Claude is not usable: rule-based Slack text only."""
    return {"claude_ok": False, "error": reason, "review": [],
            "per_pic": {d["pic"]: {"insights": [], "todos": [], "slack": fallback_slack(d, result_json["as_of"]),
                                   "dropped": 0, "error": reason} for d in result_json["digest"]}}


def generate(result_json: dict, logic: Logic, store: Store, event_days: dict, defind_text: str,
             ineligible: list[dict] | None = None, ask_fn=ask, careful: bool = True) -> dict:
    lessons = [x["text"] for x in store.lessons()]
    compare = _comparisons(result_json, store)
    style = store.get_style()
    context = {"time_gone": Windows(date.fromisoformat(result_json["as_of"])).time_gone}
    errors: list[str] = []
    fatal: list[str] = []  # first non-retryable error stops calls that have not started yet

    def call(prompt: str, schema: dict) -> dict:
        if fatal:
            raise ClaudeError(fatal[0])
        try:
            return _ask_twice(ask_fn, prompt, schema)
        except ClaudeError as e:
            if not e.retryable:
                fatal.append(str(e))
            raise
        except Exception as e:  # e.g. decode errors from the CLI – never lose the rule results
            raise ClaudeError(f"Lỗi khi gọi Claude: {e}") from e

    def one_pic(d: dict) -> tuple[str, dict]:
        pic = d["pic"]
        rows = pic_rows(result_json, pic)
        implicit = [d, context]
        fallback = fallback_slack(d, result_json["as_of"])
        if not any(d[k] for k in ("pl_high", "pl_med", "pl_trend_review", "camp_high", "camp_med", "camp_followup")):
            return pic, {"insights": [], "todos": [], "slack": fallback, "dropped": 0}
        inel = [x for x in (ineligible or []) if x.get("pic") == pic]
        implicit = implicit + [v for c in compare.get(pic, {}).values() if isinstance(c, dict) for v in
                                ([c.get("digest")] if "digest" in c else [c]) if v]
        prompt = insights_prompt(pic, rows, d, logic, lessons, style, defind_text, inel, compare.get(pic))
        try:
            draft = _verify(call(prompt, INSIGHTS_SCHEMA), rows["all"], implicit)
        except ClaudeError as e:
            errors.append(str(e))
            return pic, {"insights": [], "todos": [], "slack": fallback, "dropped": 0, "error": str(e), "steps": 1}
        final, steps = draft, 3
        if careful:
            try:
                critic = _verify(call(critic_prompt(pic, draft, rows, d, style, lessons), INSIGHTS_SCHEMA), rows["all"], implicit)
                steps = 5
                final = {"insights": critic["insights"] if critic["all_ok"] or not draft["insights"] else draft["insights"],
                         "todos": critic["todos"] if critic["all_ok"] or not draft["todos"] else draft["todos"],
                         "slack": critic["slack"] or draft["slack"], "dropped": draft["dropped"] + critic["dropped"]}
            except ClaudeError:
                pass  # the checked draft stands
        return pic, {"insights": final["insights"], "todos": final["todos"], "slack": final["slack"] or fallback,
                     "dropped": final["dropped"], "steps": steps}

    def review() -> list[dict]:
        try:
            out = call(review_prompt(result_json, logic, event_days, store.list_feedback()), REVIEW_SCHEMA)
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

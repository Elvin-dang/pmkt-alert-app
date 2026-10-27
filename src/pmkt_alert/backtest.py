"""Backtest proposed logic changes and turn feedback/review findings into approvable proposals."""
import uuid
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from .claude import ask
from .logic import Logic, valid_change, write_logic_version
from .pipeline import run_rules
from .prompts import FEEDBACK_SCHEMA, feedback_prompt
from .store import Store

KINDS = ("HIGH", "MED", "TREND")


def with_changes(logic: Logic, changes: dict) -> Logic:
    params, matrix = dict(logic.params), dict(logic.matrix)
    for key, value in changes.items():
        if key.startswith("matrix:"):
            k = key[7:]
            matrix[k] = (value or "", matrix.get(k, ("", ""))[1])
        else:
            params[key] = float(value)
    return replace(logic, params=params, matrix=matrix)


def _alerts(result) -> set[tuple[str, str]]:
    pl, camp = result.pl, result.camp
    out = {(u, s) for u, s in zip(pl.unit_id, pl.pacing_sev) if s in ("HIGH", "MED")}
    out |= {(u, "TREND") for u, t in zip(pl.unit_id, pl.trend_label) if t}
    out |= {(u, s) for u, s in zip(camp.unit_id, camp.sev) if s in ("HIGH", "MED")}
    return out


def backtest(inputs, logic: Logic, changes: dict, end: date, weeks: int = 4) -> dict:
    # ponytail: weekly snapshots (4 runs), daily replay if a weekly view hides flip-flopping alerts
    new_logic = with_changes(logic, changes)
    added = dict.fromkeys(KINDS, 0)
    removed = dict.fromkeys(KINDS, 0)
    per_week = []
    for i in range(weeks):
        as_of = end - timedelta(days=7 * i)
        old, new = _alerts(run_rules(inputs, logic, as_of)), _alerts(run_rules(inputs, new_logic, as_of))
        for _, kind in new - old:
            added[kind] += 1
        for _, kind in old - new:
            removed[kind] += 1
        per_week.append({"as_of": as_of.isoformat(), "added": len(new - old), "removed": len(old - new)})
    return {"added": added, "removed": removed, "weeks": per_week}


def _old_value(logic: Logic, key: str):
    return logic.matrix.get(key[7:], ("", ""))[0] if key.startswith("matrix:") else logic.params[key]


def _add_proposal(store: Store, p: dict) -> dict:
    p = {"id": uuid.uuid4().hex[:8], **p}
    store.save_proposals(store.proposals() + [p])
    return p


def propose_from_feedback(item: dict, row: dict, logic: Logic, store: Store, inputs, end: date, ask_fn=ask) -> dict:
    lessons = [x["text"] for x in store.lessons()]
    out = ask_fn(feedback_prompt(item, row, logic, lessons), FEEDBACK_SCHEMA)
    kind = out["kind"]
    if kind == "lesson" and out.get("lesson_text"):
        store.add_lesson(out["lesson_text"], f"feedback:{item['id']}")
        store.set_feedback_status(item["id"], "lesson")
        return {"kind": "lesson", "lesson_text": out["lesson_text"], "rationale": out["rationale"]}
    key, value = out.get("param_key") or "", out.get("proposed_value")
    if kind == "param" and valid_change(key, value, logic):
        p = _add_proposal(store, {"source": "feedback", "feedback_id": item["id"], "param_key": key,
                                  "old": _old_value(logic, key), "new": value, "rationale": out["rationale"],
                                  "title": item.get("text", "")[:80], "backtest": backtest(inputs, logic, {key: value}, end),
                                  "status": "pending"})
    else:
        p = _add_proposal(store, {"source": "feedback", "feedback_id": item["id"], "param_key": None, "old": None,
                                  "new": None, "rationale": out["rationale"], "title": item.get("text", "")[:80],
                                  "backtest": None, "status": "saved_rule"})
        kind = "rule"
    store.set_feedback_status(item["id"], "proposed")
    return {"kind": kind, "proposal": p}


def proposals_from_review(findings: list[dict], logic: Logic, store: Store, inputs, end: date) -> None:
    pending = {(p["param_key"], p["new"]) for p in store.proposals() if p["status"] == "pending"}
    for f in findings:
        key, value = f.get("param_key") or "", f.get("proposed_value")
        if f["kind"] != "param" or not valid_change(key, value, logic) or (key, value) in pending:
            continue
        _add_proposal(store, {"source": "review", "feedback_id": None, "param_key": key, "old": _old_value(logic, key),
                              "new": value, "rationale": f["detail"], "title": f["title"],
                              "backtest": backtest(inputs, logic, {key: value}, end), "status": "pending"})
        pending.add((key, value))


def apply_approved(store: Store, logic: Logic) -> Path:
    approved = [p for p in store.proposals() if p["status"] == "approved"]
    if not approved:
        raise ValueError("Chưa có đề xuất nào được duyệt")
    changes = {p["param_key"]: p["new"] for p in approved}
    note = "; ".join(f"{p['param_key']} {p['old']}→{p['new']}" for p in approved)
    out = write_logic_version(logic, changes, note, store.base / "logic")
    store.save_settings({"active_logic": out.name})
    for p in approved:
        store.set_proposal_status(p["id"], "applied")
        if p.get("feedback_id"):
            store.set_feedback_status(p["feedback_id"], "applied")
    return out

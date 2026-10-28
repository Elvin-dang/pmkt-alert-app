"""Estimated time left for a run, learned from earlier runs (smoothed average per step and per Claude call)."""
import time


class Eta:
    DEFAULTS = {"load": 5.0, "logic": 1.0, "rules": 5.0, "logic_eval": 15.0, "claude_call": 25.0}

    def __init__(self, history: dict | None, parallel: int = 4):
        self.avg = {**self.DEFAULTS, **(history or {})}
        self.parallel = parallel
        self.steps: list[str] = []
        self.started: dict[str, float] = {}
        self.finished: set[str] = set()
        self.calls_total = self.calls_left = 0

    def plan(self, steps: list[str], claude_calls: int) -> None:
        self.steps, self.calls_total, self.calls_left = list(steps), claude_calls, claude_calls

    def _expected(self, step: str) -> float:
        if step == "claude":
            return self.calls_left * self.avg["claude_call"] / self.parallel
        return self.avg.get(step, 0.0)

    def remaining(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        left = 0.0
        for s in self.steps:
            if s in self.finished:
                continue
            exp = self._expected(s)
            if s in self.started and s != "claude":  # Claude counts down by calls finished instead
                exp = max(0.0, exp - (now - self.started[s]))
            left += exp
        return left

    def start(self, step: str, now: float | None = None) -> None:
        self.started.setdefault(step, time.monotonic() if now is None else now)

    def calls_done(self, n: int = 1) -> None:
        self.calls_left = max(0, self.calls_left - n)

    def done(self, step: str, now: float | None = None) -> None:
        if step in self.finished:
            return
        self.finished.add(step)
        if step not in self.started:  # skipped (e.g. Claude offline): nothing to learn
            return
        took = (time.monotonic() if now is None else now) - self.started[step]
        key, value = step, took
        if step == "claude":
            done_calls = self.calls_total - self.calls_left
            if not done_calls:
                return
            key, value = "claude_call", took * self.parallel / done_calls
        self.avg[key] = 0.5 * self.avg.get(key, value) + 0.5 * value

    def learned(self) -> dict:
        return dict(self.avg)

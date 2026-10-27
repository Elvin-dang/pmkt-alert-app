"""Verbatim label strings from Alert_Logic_Ver 1 (PL_Alert / Campaign_Alert formulas)."""
NO_PLAN = "NO PLAN – kiểm tra target"
NOT_RUNNING = "KHÔNG CHẠY – spend ~0 so với plan"
SCALE_DOWN = "SCALE DOWN – overspend + TACoS vượt"
OPTIMIZE_ACOS = "OPTIMIZE ACoS – TACoS vượt target"
PL_SCALE_UP = "SCALE UP – còn room, TACoS trong target"
BUDGET_CAP = "BUDGET CAP – đã dùng hết budget tháng"
CHECK = "CHECK – GMV thiếu nhưng spend không thấp (listing/stock/giá?)"
MAINTAIN = "MAINTAIN"

WAIT = "WAIT – chưa đủ click"
PAUSE = "PAUSE/NEGATE – đủ click, 0 order"
CHECK_PLAN = "CHECK PLAN – PL chưa có target"
CUT = "CUT/OPTIMIZE – ACoS > PL avg"
PUSH = "MAINTAIN/PUSH – ACoS dưới PL avg"
WATCH = "WATCH"
CAMP_SCALE_UP = "SCALE UP – tăng bid/budget"
OPTIMIZE = "OPTIMIZE – ACoS cao"

WORSE_BOTH = "XẤU ĐI 7D: Spend ↑ & ACoS ↑"
WORSE_ACOS = "XẤU ĐI 7D: ACoS ↑"
BETTER_ACOS = "TỐT LÊN 7D: ACoS ↓"

NOT_ACTIONED = "CHƯA ACTION"
ACTIONED = "ĐÃ ACTION"
OLD_ACTION = "ACTION CŨ"


def div(a: float, b: float, zero=0.0):
    return zero if not b else a / b

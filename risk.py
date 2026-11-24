import time
from decimal import Decimal

from utils import floor_to


class Risk:
    def __init__(self, p, db):
        self.p, self.db = p, db

    def update(self, eq, now):
        t = time.gmtime(now)
        day, wk = time.strftime("%Y-%m-%d", t), time.strftime("%G-%V", t)
        if self.db.get("day") != day:
            self.db.set("day", day); self.db.set("day_eq", eq)
        if self.db.get("week") != wk:
            self.db.set("week", wk); self.db.set("week_eq", eq)
        peak = max(float(self.db.get("peak") or 0), eq)
        self.db.set("peak", peak)
        d0, w0 = float(self.db.get("day_eq")), float(self.db.get("week_eq"))
        if eq <= peak * (1 - self.p.dd_kill_pct):
            return "kill"
        if self.db.get("paused") == "1" or eq <= peak * (1 - self.p.dd_pause_pct):
            self.db.set("paused", "1")      # manual reset: meta table mein paused=0
            return "pause"
        if eq <= d0 * (1 - self.p.daily_loss_pct): return "day_limit"
        if eq <= w0 * (1 - self.p.weekly_loss_pct): return "week_limit"
        return "ok"

    def allow(self, eq, pos, funding, side):
        p = self.p
        if len(pos) >= p.max_positions:
            return False, "max_positions"
        open_risk = 0.0
        for x in pos.values():
            d = 1 if x.get("side", "long") == "long" else -1
            open_risk += max(0, d * (x["entry"] - x["stop"])) * x["qty"]
        if open_risk + eq * p.risk_pct > eq * p.max_open_risk_pct:
            return False, "open_risk"
        if side == "long" and funding > p.max_funding:
            return False, "funding"
        if side == "short" and funding < -p.max_funding:
            return False, "funding"
        return True, "ok"

    def size(self, eq, entry, stop, f, pos):
        p = self.p
        per_unit = abs(entry - stop) + 2 * entry * (p.fee_rate + p.slip_rate)
        if per_unit <= 0:
            return None
        qty = Decimal(str(eq * p.risk_pct / per_unit))
        room = eq * p.max_notional_x - sum(x["qty"] * x["entry"] for x in pos.values())
        if room <= 0:
            return None
        qty = floor_to(min(qty, Decimal(str(room / entry))), f["step"])
        qty = min(qty, f["max_qty"])
        if qty < f["min_qty"] or qty * Decimal(str(entry)) < f["min_notional"] * Decimal("1.05"):
            return None
        return qty
import time
from decimal import Decimal

from binance_client import BinanceError
from config import ACCOUNT_PATH, POSRISK_PATH
from utils import floor_to, fmt, log


class StopFailed(Exception): pass

def D(side): return 1 if side == "long" else -1


class ShadowBroker:
    """Paper account, live data par. Koi order exchange ko nahi jaata."""
    def __init__(self, p):
        self.p, self.cash, self.pos = p, p.start_equity, {}

    def equity(self, marks):
        return self.cash + sum(D(x["side"]) * (marks.get(s, x["entry"]) - x["entry"]) * x["qty"]
                               for s, x in self.pos.items())

    def open_symbols(self): return set(self.pos)

    def open(self, sym, side, qty, stop, ref, f):
        fill, q = ref * (1 + D(side) * self.p.slip_rate), float(qty)
        self.cash -= fill * q * self.p.fee_rate
        self.pos[sym] = dict(side=side, qty=q, entry=fill, stop=stop)
        return fill, q

    def move_stop(self, sym, side, stop, qty, f):
        self.pos[sym]["stop"] = stop

    def _exit(self, sym, fill):
        x = self.pos.pop(sym)
        self.cash += D(x["side"]) * (fill - x["entry"]) * x["qty"] - fill * x["qty"] * self.p.fee_rate

    def close(self, sym, ref, why):
        d = D(self.pos[sym]["side"])
        fill = ref * (1 - d * self.p.slip_rate)
        self._exit(sym, fill)
        return fill

    def sweep(self, bars, tracked):
        out = []
        for s in list(self.pos):
            x, b = self.pos[s], bars.get(s)
            if not b: continue
            d = D(x["side"])
            if d == 1 and b["low"] <= x["stop"]:
                fill = min(x["stop"], b["open"]) * (1 - self.p.slip_rate)
            elif d == -1 and b["high"] >= x["stop"]:
                fill = max(x["stop"], b["open"]) * (1 + self.p.slip_rate)
            else:
                continue
            self._exit(s, fill)
            out.append((s, fill, "stop"))
        return out

    def ensure_stops(self, pos, filt): pass


class LiveBroker:
    def __init__(self, cl, p):
        self.cl, self.p = cl, p
        self.ready, self.algo = set(), {}

    def equity(self, marks=None):
        return float(self.cl.signed("GET", ACCOUNT_PATH)["totalMarginBalance"])

    def open_symbols(self):
        rows = self.cl.signed("GET", POSRISK_PATH)
        return {r["symbol"] for r in rows if float(r["positionAmt"]) != 0}

    def _prep(self, sym):
        if sym in self.ready: return
        try:
            self.cl.signed("POST", "/fapi/v1/marginType", symbol=sym, marginType="ISOLATED")
        except BinanceError as e:
            if '"code":-4046' not in e.body: raise
        self.cl.signed("POST", "/fapi/v1/leverage", symbol=sym, leverage=self.p.leverage)
        self.ready.add(sym)

    def _place_stop(self, sym, side, stop, qty, f):
        px = floor_to(Decimal(str(stop)), f["tick"])
        if side == "short":
            px += f["tick"]                       # short ka stop upar round
        r = self.cl.signed("POST", "/fapi/v1/algoOrder",
            algoType="CONDITIONAL", symbol=sym,
            side="SELL" if side == "long" else "BUY", type="STOP_MARKET",
            quantity=fmt(qty), triggerPrice=fmt(px), reduceOnly="true",
            workingType="MARK_PRICE", clientAlgoId=f"sl{sym}{int(time.time())}")
        self.algo[sym] = r.get("algoId")

    def _cancel_stop(self, sym):
        aid = self.algo.pop(sym, None)
        if aid is None: return
        try:
            self.cl.signed("DELETE", "/fapi/v1/algoOrder", algoId=aid)
        except BinanceError:
            pass

    def open(self, sym, side, qty, stop, ref, f):
        self._prep(sym)
        eside, xside = ("BUY", "SELL") if side == "long" else ("SELL", "BUY")
        r = self.cl.signed("POST", "/fapi/v1/order", symbol=sym, side=eside,
                           type="MARKET", quantity=fmt(qty), newOrderRespType="RESULT")
        filled = Decimal(r.get("executedQty") or fmt(qty))
        fill = float(r.get("avgPrice") or 0) or ref
        try:
            self._place_stop(sym, side, stop, filled, f)
        except Exception as e:      # FAIL-SAFE: bina stop ke position nahi
            self.cl.signed("POST", "/fapi/v1/order", symbol=sym, side=xside,
                           type="MARKET", quantity=fmt(filled), reduceOnly="true")
            raise StopFailed(str(e))
        return fill, float(filled)

    def move_stop(self, sym, side, stop, qty, f):
        old = self.algo.get(sym)
        self._place_stop(sym, side, stop, Decimal(str(qty)), f)   # pehle naya
        if old is not None:                                       # phir purana cancel
            try: self.cl.signed("DELETE", "/fapi/v1/algoOrder", algoId=old)
            except BinanceError: pass

    def close(self, sym, ref, why):
        self._cancel_stop(sym)
        rows = self.cl.signed("GET", POSRISK_PATH, symbol=sym)
        amt = float(rows[0]["positionAmt"]) if rows else 0.0
        if amt:
            self.cl.signed("POST", "/fapi/v1/order", symbol=sym,
                           side="SELL" if amt > 0 else "BUY", type="MARKET",
                           quantity=fmt(Decimal(str(abs(amt)))), reduceOnly="true")
        return ref

    def sweep(self, bars, tracked):
        open_now = self.open_symbols()
        out = []
        for s in tracked:
            if s not in open_now:
                self._cancel_stop(s)
                out.append((s, None, "stop_or_external"))
        return out

    def ensure_stops(self, pos, filt):
        for s, x in pos.items():
            r = self.cl.signed("GET", "/fapi/v1/openAlgoOrders", symbol=s)
            rows = r if isinstance(r, list) else r.get("orders", r.get("data", []))
            if rows:
                self.algo[s] = rows[0].get("algoId"); continue
            log("ALERT stop missing", s, "-> dobara laga raha hu")
            try:
                self._place_stop(s, x.get("side", "long"), x["stop"], Decimal(str(x["qty"])), filt[s])
            except Exception:
                self.close(s, 0, "no_stop")
                raise SystemExit(f"{s}: stop nahi laga, position close ki")
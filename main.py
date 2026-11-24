import json
import os
import time
import traceback
from decimal import Decimal

from binance_client import Binance
from broker import LiveBroker, ShadowBroker, StopFailed
from config import *
from db import DB
from indicators import atr, ema, klines
from risk import Risk
from signals import evaluate
from utils import log

STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "EUR", "AEUR"}

def dr(side): return 1 if side == "long" else -1

def parse_filters(s):
    f = {x["filterType"]: x for x in s["filters"]}
    lot = f.get("MARKET_LOT_SIZE", f["LOT_SIZE"])
    return {"step": Decimal(lot["stepSize"]), "min_qty": Decimal(lot["minQty"]),
            "max_qty": Decimal(lot["maxQty"]), "tick": Decimal(f["PRICE_FILTER"]["tickSize"]),
            "min_notional": Decimal(f["MIN_NOTIONAL"]["notional"])}

def load_state():
    try: return json.load(open("state.json"))
    except FileNotFoundError: return {"pos": {}, "cool": {}}

def save_state(S):
    with open("state.tmp", "w") as f:
        json.dump(S, f)
    for _ in range(10):
        try:
            os.replace("state.tmp", "state.json")
            return
        except PermissionError:
            time.sleep(0.3)
    log("WARN: state.json replace fail")

class Bot:
    def __init__(self):
        self.p, self.db = P(), DB()
        self.risk = Risk(self.p, self.db)
        self.cl = Binance(BASE_URL, API_KEY, API_SECRET); self.cl.sync_time()
        self.S = load_state()
        self.uni, self.filt, self.uni_day = [], {}, None
        self.refresh_universe()
        if MODE == "shadow":
            self.broker = ShadowBroker(self.p)
            self.broker.cash = self.S.get("cash", self.p.start_equity)
            self.broker.pos = self.S.get("spos", {})
        else:
            self.broker = LiveBroker(self.cl, self.p)
            if self.cl.signed("GET", "/fapi/v1/positionSide/dual").get("dualSidePosition"):
                raise SystemExit("Hedge mode ON hai. One-way mode karo.")
            ex, st = self.broker.open_symbols(), set(self.S["pos"])
            if ex != st:
                raise SystemExit(f"State mismatch exchange={ex} state={st}. Manually theek karo.")
            self.broker.ensure_stops(self.S["pos"], self.filt)

    def refresh_universe(self):
        info = self.cl.get("/fapi/v1/exchangeInfo")
        now, ok = time.time() * 1000, {}
        for s in info["symbols"]:
            if (s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
                    and s["status"] == "TRADING" and s["baseAsset"] not in STABLES
                    and now - s["onboardDate"] > self.p.min_listing_days * 86400000):
                ok[s["symbol"]] = parse_filters(s)
        tk = [t for t in self.cl.get("/fapi/v1/ticker/24hr") if t["symbol"] in ok]
        tk.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
        self.uni = [t["symbol"] for t in tk[: self.p.universe_n]]
        self.filt = ok
        log("universe:", ",".join(self.uni))

    def finish(self, s, px, why):
        x = self.S["pos"].pop(s)
        px = px or x["stop"]
        pnl = dr(x.get("side", "long")) * (px - x["entry"]) * x["qty"]
        self.db.trade(s, x, px, why, pnl, int(time.time()))
        self.S["cool"][s] = time.time() + self.p.cooldown_bars * 3600
        log(f"EXIT {s} {x.get('side','long')} {why} px={px:.6g} pnl~{pnl:.2f}")

    def manage_one(self, s, x, d1, d4, mark):
        p, d = self.p, dr(x["side"])
        l1, l4 = d1.iloc[-1], d4.iloc[-1]
        c = float(l1.close)
        x["bars_held"] += 1
        x["ext"] = max(x["ext"], c) if d == 1 else min(x["ext"], c)
        R = abs(x["entry"] - x["init_stop"])
        r_now = d * (c - x["entry"]) / R if R > 0 else 0
        e50 = ema(d4.close, 50).iloc[-1]
        if (d == 1 and l4.close < e50) or (d == -1 and l4.close > e50):
            return "trend_end"
        if x["bars_held"] == p.time_stop_bars and r_now < p.time_stop_r:
            return "time_stop"
        if int(d4.index[-1]) != x["last4"]:                 # naya 4H bar close hua
            x["last4"] = int(d4.index[-1])
            a4 = float(atr(d4).iloc[-1])
            if d == 1:
                trail = x["ext"] - p.trail_atr * a4
                better = trail > x["stop"] * 1.0005 and trail < mark * 0.998
            else:
                trail = x["ext"] + p.trail_atr * a4
                better = trail < x["stop"] * 0.9995 and trail > mark * 1.002
            if better:
                self.broker.move_stop(s, x["side"], trail, x["qty"], self.filt[s])
                log(f"TRAIL {s} {x['side']} {x['stop']:.6g} -> {trail:.6g}")
                x["stop"] = trail
        return None

    def on_bar(self, bar_ts, entries=True):
        p, S, cl = self.p, self.S, self.cl
        day = time.strftime("%Y-%m-%d", time.gmtime(bar_ts))
        if day != self.uni_day:
            if self.uni_day: self.refresh_universe()
            self.uni_day = day
        marks = {t["symbol"]: float(t["price"]) for t in cl.get("/fapi/v1/ticker/price")}
        btc4 = klines(cl, "BTCUSDT", "4h")

        bars = {s: klines(cl, s, "1h", 5).iloc[-1].to_dict() for s in S["pos"]}
        for s, px, why in self.broker.sweep(bars, list(S["pos"])):
            self.finish(s, px, why)

        eq = self.broker.equity(marks)
        self.db.equity(bar_ts, eq)
        st = self.risk.update(eq, bar_ts)
        log(f"equity={eq:.2f} risk_state={st} open={[(s, x.get('side','long')) for s, x in S['pos'].items()]}")
        if st == "kill":
            for s in list(S["pos"]):
                self.finish(s, self.broker.close(s, marks[s], "kill"), "kill")
            save_state(S); raise SystemExit("KILL SWITCH: drawdown limit")

        extra = self.broker.open_symbols() - set(S["pos"])
        if extra:
            log("ALERT: exchange par unknown position", extra, "-> entries band"); entries = False

        for s in list(S["pos"]):
            x = S["pos"][s]
            x.setdefault("side", "long"); x.setdefault("ext", x.get("highest", x["entry"]))
            why = self.manage_one(s, x, klines(cl, s, "1h", 60), klines(cl, s, "4h", 200), marks[s])
            if why: self.finish(s, self.broker.close(s, marks[s], why), why)

        book = {b["symbol"]: b for b in cl.get("/fapi/v1/ticker/bookTicker")}
        fund = {x["symbol"]: float(x["lastFundingRate"]) for x in cl.get("/fapi/v1/premiumIndex")}
        cands = []
        for s in self.uni:
            if s in S["pos"] or S["cool"].get(s, 0) > time.time() or s not in book: continue
            ask, bid = float(book[s]["askPrice"]), float(book[s]["bidPrice"])
            spread = (ask - bid) / ask * 100
            try:
                sigs = evaluate(s, klines(cl, s, "1h"), klines(cl, s, "4h"), btc4,
                                {"spread_pct": spread}, p)
            except Exception as e:
                log(f"scan fail {s}: {type(e).__name__}"); continue
            for g in sigs:
                self.db.scan(bar_ts, g)
                if g.ok: cands.append(g)
        nl = sum(g.side == "long" for g in cands)
        log(f"scan done: {len(self.uni)} coins, signals long={nl} short={len(cands) - nl}")

        if entries and st == "ok":
            for g in sorted(cands, key=lambda g: (g.soft_pass, g.adx4), reverse=True):
                s, side = g.symbol, g.side
                d = dr(side)
                ask, bid = float(book[s]["askPrice"]), float(book[s]["bidPrice"])
                spread = (ask - bid) / ask * 100
                ref = ask if d == 1 else bid
                broke = ask > g.breakout if d == 1 else bid < g.breakout
                gap = d * (ref - g.close)
                if not (broke and gap <= p.gap_atr_max * g.atr1h and spread <= p.max_spread_pct):
                    log(f"skip {s} {side}: confirm fail"); continue
                ok, why = self.risk.allow(eq, S["pos"], fund.get(s, 0), side)
                if not ok:
                    log(f"skip {s} {side}: {why}")
                    if why in ("max_positions", "open_risk"): break
                    continue
                stop = ref - d * p.stop_atr * g.atr1h
                qty = self.risk.size(eq, ref, stop, self.filt[s], S["pos"])
                if not qty: log(f"skip {s} {side}: size"); continue
                try:
                    fill, q = self.broker.open(s, side, qty, stop, ref, self.filt[s])
                except StopFailed as e:
                    log(f"ALERT {s}: stop fail, position band ki: {e}"); continue
                except Exception as e:
                    log(f"ALERT {s}: order error {e}"); continue
                S["pos"][s] = dict(side=side, qty=q, entry=fill, stop=stop, init_stop=stop,
                                   ext=ref, bars_held=0, last4=g.t4)
                log(f"ENTRY {s} {side} qty={q} fill={fill:.6g} stop={stop:.6g} soft={g.soft_pass}/8")

        if MODE == "shadow":
            S["cash"], S["spos"] = self.broker.cash, self.broker.pos
        save_state(S)

if __name__ == "__main__":
    bot = Bot()
    from catchup import catch_up
    catch_up(bot, save_state)                # chhute hue ghanto ka hisaab
    last = int(time.time() // 3600) * 3600
    bot.on_bar(last, entries=False)          # pipeline check, entry nahi
    while True:
        now = time.time(); bar = int(now // 3600) * 3600
        if bar != last and now - bar >= 5:
            last = bar
            try: bot.on_bar(bar)
            except SystemExit: raise
            except Exception: log("ERROR\n" + traceback.format_exc())
        time.sleep(1)
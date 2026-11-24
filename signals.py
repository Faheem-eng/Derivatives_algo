from dataclasses import dataclass

from indicators import adx, atr, ema, rsi


@dataclass
class Signal:
    symbol: str
    side: str
    t1: int
    t4: int
    ok: bool
    hard: dict
    soft: dict
    soft_pass: int
    close: float
    atr1h: float
    adx4: float
    breakout: float
    vals: dict

def evaluate(sym, d1, d4, b4, ctx, p):
    """Ek coin ke liye [long_signal, short_signal] return karta hai."""
    c4, c1 = d4.close, d1.close
    e50, e200 = ema(c4, 50), ema(c4, 200)
    adx4, adx1 = float(adx(d4).iloc[-1]), float(adx(d1).iloc[-1])
    last = d1.iloc[-1]
    a1s = atr(d1)
    atr1 = float(a1s.iloc[-1])
    hi20 = float(d1.high.shift(1).rolling(p.donchian).max().iloc[-1])
    lo20 = float(d1.low.shift(1).rolling(p.donchian).min().iloc[-1])
    e20 = float(ema(c1, 20).iloc[-1])
    btc_c, btc_e200 = b4.close.iloc[-1], ema(b4.close, 200).iloc[-1]
    rng = last.high - last.low
    body_ok = rng > 0 and abs(last.close - last.open) / rng >= 0.5
    vmed = float(d1.volume.iloc[-21:-1].median())
    r = float(rsi(c1).iloc[-1])
    atr_pct = a1s / c1
    pct = float((atr_pct.iloc[-200:] < atr_pct.iloc[-1]).mean() * 100)
    coin_ret, btc_ret = c4.pct_change(20).iloc[-1], b4.close.pct_change(20).iloc[-1]
    h_now, h_prev = d4.high.iloc[-10:].max(), d4.high.iloc[-20:-10].max()
    l_now, l_prev = d4.low.iloc[-10:].min(), d4.low.iloc[-20:-10].min()
    g1 = ctx["spread_pct"] <= p.max_spread_pct
    vol_ok = last.volume >= p.vol_mult * vmed

    long_hard = {
        "G1_liquidity": g1,
        "G2_ema_stack": e50.iloc[-1] > e200.iloc[-1],
        "G3_close_ema50": c4.iloc[-1] > e50.iloc[-1],
        "G4_adx4h": adx4 >= p.adx4h_min,
        "G5_btc_regime": btc_c > btc_e200,
        "G6_breakout": last.close > hi20,
        "G7_no_chase": (last.close - e20) <= p.chase_atr * atr1,
    }
    long_soft = {
        "S1_adx1h": adx1 >= p.adx1h_min,
        "S2_volume": vol_ok,
        "S3_rsi": 55 <= r <= 75,
        "S4_slope": e50.iloc[-1] > e50.iloc[-7],
        "S5_atr_pct": 30 <= pct <= 80,
        "S6_candle": rng > 0 and (last.close - last.low) / rng >= 0.7 and body_ok,
        "S7_structure": bool(h_now > h_prev and l_now > l_prev),
        "S8_rel_str": coin_ret > btc_ret,
    }
    short_hard = {
        "G1_liquidity": g1,
        "G2_ema_stack": e50.iloc[-1] < e200.iloc[-1],
        "G3_close_ema50": c4.iloc[-1] < e50.iloc[-1],
        "G4_adx4h": adx4 >= p.adx4h_min,
        "G5_btc_regime": btc_c < btc_e200,
        "G6_breakout": last.close < lo20,
        "G7_no_chase": (e20 - last.close) <= p.chase_atr * atr1,
    }
    short_soft = {
        "S1_adx1h": adx1 >= p.adx1h_min,
        "S2_volume": vol_ok,
        "S3_rsi": 25 <= r <= 45,
        "S4_slope": e50.iloc[-1] < e50.iloc[-7],
        "S5_atr_pct": 30 <= pct <= 80,
        "S6_candle": rng > 0 and (last.high - last.close) / rng >= 0.7 and body_ok,
        "S7_structure": bool(h_now < h_prev and l_now < l_prev),
        "S8_rel_str": coin_ret < btc_ret,
    }
    vals = dict(close=float(last.close), atr1h=atr1, adx4h=adx4, adx1h=adx1,
                rsi=r, atr_pct_rank=pct, spread=ctx["spread_pct"])

    def pack(side, hard, soft, brk):
        hard = {k: bool(v) for k, v in hard.items()}
        soft = {k: bool(v) for k, v in soft.items()}
        sp = sum(soft.values())
        return Signal(sym, side, int(d1.index[-1]), int(d4.index[-1]),
                      all(hard.values()) and sp >= p.soft_min, hard, soft, sp,
                      float(last.close), atr1, adx4, brk, {**vals, "breakout": brk})

    return [pack("long", long_hard, long_soft, hi20),
            pack("short", short_hard, short_soft, lo20)]
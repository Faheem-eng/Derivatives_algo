import time

import numpy as np
import pandas as pd


def klines(cl, sym, interval, limit=300):
    raw = cl.get("/fapi/v1/klines", symbol=sym, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=["t","open","high","low","close","volume","ct",
                                    "qv","n","tb","tq","i"])
    df = df[["t","open","high","low","close","volume","ct"]].copy()
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    now_ms = int(time.time() * 1000) + cl.offset
    df = df[df["ct"] < now_ms]          # sirf closed candles
    return df.set_index("t")

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rma(s, n): return s.ewm(alpha=1 / n, adjust=False).mean()

def true_range(df):
    pc = df.close.shift(1)
    return pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()],
                     axis=1).max(axis=1)

def atr(df, n=14): return rma(true_range(df), n)

def adx(df, n=14):
    up, dn = df.high.diff(), -df.low.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi, mdi = 100 * rma(plus, n) / a, 100 * rma(minus, n) / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return rma(dx, n)

def rsi(close, n=14):
    d = close.diff()
    g, l = rma(d.clip(lower=0), n), rma((-d).clip(lower=0), n)
    return 100 - 100 / (1 + g / l)
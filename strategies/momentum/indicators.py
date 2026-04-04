import numpy as np
import pandas as pd

def add_ema(df, period, col="close"):
    return df[col].ewm(span=period, adjust=False).mean()

def add_atr(df, period):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def add_adx(df, period):
    high, low, close = df["high"], df["low"], df["close"]
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    up   = high - prev_high
    down = prev_low - low
    plus_dm  = pd.Series(np.where((up > down)  & (up > 0),   up,   0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up)  & (down > 0), down, 0.0), index=df.index)
    atr_s    = tr.ewm(span=period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean()

def add_htf_ema(df_15m, period):
    close_4h = df_15m["close"].resample("4h").last().dropna()
    ema_4h   = close_4h.ewm(span=period, adjust=False).mean()
    return ema_4h.reindex(df_15m.index, method="ffill")

def populate_indicators(df, params):
    df = df.copy()
    df["ema_fast"] = add_ema(df, params["fast_ema"])
    df["ema_slow"] = add_ema(df, params["slow_ema"])
    df["atr"]      = add_atr(df, params["atr_period"])
    df["adx"]      = add_adx(df, params["adx_period"])
    df["htf_ema"]  = add_htf_ema(df, params["htf_ema"])
    return df

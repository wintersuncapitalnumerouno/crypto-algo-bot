# =============================================================
# strategies/ema16/strategy.py — v5
# =============================================================
# Single change from v4:
#   stop_loss_long  = close - ATR × atr_stop_mult
#   stop_loss_short = close + ATR × atr_stop_mult
#   atr_stop_pct    = (ATR × atr_stop_mult) / close
#
# Engine reads atr_stop_pct for position sizing when
# df.attrs["use_atr_stop"] = True.
#
# All entry logic, RSI filter, resampling, trailing stop,
# scaled exits — identical to v4.
# =============================================================

import pandas as pd
import numpy as np
from strategies.ema16.params import get_default_params


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs    = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def get_entries_exits(df: pd.DataFrame, params: dict = None):
    p = {**get_default_params(), **(params or {})}

    # ── Resample 5m → 4h (unchanged) ─────────────────────────
    df = df.resample("4h").agg({
        "open": "first", "high": "max",
        "low": "min", "close": "last", "volume": "sum"
    }).dropna().copy()

    # ── Indicators ────────────────────────────────────────────
    df["ema16"] = df["close"].ewm(span=p["ema_period"], adjust=False).mean()
    df["rsi"]   = compute_rsi(df["close"], period=p["rsi_period"])
    df["atr"]   = compute_atr(df, period=p["atr_period"])

    # Diagnostic aliases (unchanged)
    df["ema_fast"] = df["ema16"]
    df["ema_slow"] = df["ema16"]
    df["adx"]      = 0.0

    # ── Entry signals (identical to v4) ───────────────────────
    prev_close = df["close"].shift(1)
    prev_ema   = df["ema16"].shift(1)

    cross_above = (df["close"] > df["ema16"]) & (prev_close <= prev_ema)
    cross_below = (df["close"] < df["ema16"]) & (prev_close >= prev_ema)

    rsi_long  = (df["rsi"] >= p["rsi_long_min"])  & (df["rsi"] <= p["rsi_long_max"])
    rsi_short = (df["rsi"] >= p["rsi_short_min"]) & (df["rsi"] <= p["rsi_short_max"])

    df["signal"] = 0
    df.loc[cross_above & rsi_long,  "signal"] =  1
    df.loc[cross_below & rsi_short, "signal"] = -1

    # ── ATR-based stop (only change vs v4) ────────────────────
    atr_mult = p["atr_stop_mult"]

    df["stop_loss_long"]    = df["close"] - df["atr"] * atr_mult
    df["stop_loss_short"]   = df["close"] + df["atr"] * atr_mult

    # atr_stop_pct: used by engine for position sizing
    # replaces config.STOP_PCT when use_atr_stop = True
    df["atr_stop_pct"] = (df["atr"] * atr_mult) / df["close"]

    # No fixed TP — scaled exits handle this (same as v4)
    # Engine will use tp_levels from attrs
    df["take_profit_long"]  = df["close"] * 9.0   # disabled placeholder
    df["take_profit_short"] = df["close"] * 0.1   # disabled placeholder

    # ── Engine attrs (identical to v4 except use_atr_stop) ────
    df.attrs["trail_trigger"] = p["trail_trigger"]
    df.attrs["trail_offset"]  = p["trail_offset"]
    df.attrs["tp_levels"]     = [
        (0.02,  0.40),
        (0.025, 0.30),
        (0.03,  0.30),
    ]
    df.attrs["use_atr_stop"]  = True   # new in v5

    # ── Warmup ────────────────────────────────────────────────
    warmup = max(p["ema_period"] * 2, p["rsi_period"] * 2, p["atr_period"] * 2)
    df     = df.iloc[warmup:].copy()

    long_entries  = df["signal"] == 1
    short_entries = df["signal"] == -1
    long_exits    = df["signal"] == -1
    short_exits   = df["signal"] ==  1

    return long_entries, short_entries, short_exits, long_exits, df

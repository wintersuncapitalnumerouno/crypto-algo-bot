# =============================================================
# strategies/ema16/strategy.py
# =============================================================
# Shared signal function for all EMA16 versions.
# Behavior is controlled entirely by params passed in.
#
# V4 params (params_v4.py):
#   - no atr_period / atr_stop_mult keys
#   - engine uses fixed stop (config.STOP_PCT)
#
# V5 params (params_v5.py):
#   - atr_period + atr_stop_mult present
#   - df.attrs["use_atr_stop"] = True
#   - engine uses stop_loss_long/short + atr_stop_pct columns
#
# This file never imports from params.py directly.
# Params are always injected by the registry.
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
    # params injected by registry — never read from params.py here
    p = {**get_default_params(), **(params or {})}

    # ── Resample 5m → 4h ──────────────────────────────────────
    df = df.resample("4h").agg({
        "open": "first", "high": "max",
        "low": "min", "close": "last", "volume": "sum"
    }).dropna().copy()

    # ── Core indicators ───────────────────────────────────────
    df["ema16"] = df["close"].ewm(span=p["ema_period"], adjust=False).mean()
    df["rsi"]   = compute_rsi(df["close"], period=p["rsi_period"])

    # Diagnostic aliases
    df["ema_fast"] = df["ema16"]
    df["ema_slow"] = df["ema16"]
    df["adx"]      = 0.0

    # ── Entry signals ─────────────────────────────────────────
    prev_close  = df["close"].shift(1)
    prev_ema    = df["ema16"].shift(1)
    cross_above = (df["close"] > df["ema16"]) & (prev_close <= prev_ema)
    cross_below = (df["close"] < df["ema16"]) & (prev_close >= prev_ema)

    rsi_long  = (df["rsi"] >= p["rsi_long_min"])  & (df["rsi"] <= p["rsi_long_max"])
    rsi_short = (df["rsi"] >= p["rsi_short_min"]) & (df["rsi"] <= p["rsi_short_max"])

    df["signal"] = 0
    df.loc[cross_above & rsi_long,  "signal"] =  1
    df.loc[cross_below & rsi_short, "signal"] = -1

    # ── Stop loss — ATR or fixed depending on params ──────────
    use_atr = "atr_period" in p and "atr_stop_mult" in p

    if use_atr:
        # V5+: ATR-based stop
        df["atr"]               = compute_atr(df, period=p["atr_period"])
        atr_mult                = p["atr_stop_mult"]
        df["stop_loss_long"]    = df["close"] - df["atr"] * atr_mult
        df["stop_loss_short"]   = df["close"] + df["atr"] * atr_mult
        df["atr_stop_pct"]      = (df["atr"] * atr_mult) / df["close"]
        df["take_profit_long"]  = df["close"] * 9.0    # disabled — scaled exits handle it
        df["take_profit_short"] = df["close"] * 0.1    # disabled
        df.attrs["use_atr_stop"] = True
    else:
        # V4: no ATR columns set — engine uses config.STOP_PCT
        # take_profit also not set — engine default (4%) applies
        df.attrs["use_atr_stop"] = False

    # ── Engine attrs (all versions) ───────────────────────────
    df.attrs["trail_trigger"] = p["trail_trigger"]
    df.attrs["trail_offset"]  = p["trail_offset"]
    df.attrs["tp_levels"]     = [
        (0.02,  0.40),
        (0.025, 0.30),
        (0.03,  0.30),
    ]

    # ── Warmup ────────────────────────────────────────────────
    atr_period = p.get("atr_period", 0)
    warmup     = max(p["ema_period"] * 2, p["rsi_period"] * 2, atr_period * 2)
    df         = df.iloc[warmup:].copy()

    long_entries  = df["signal"] == 1
    short_entries = df["signal"] == -1
    long_exits    = df["signal"] == -1
    short_exits   = df["signal"] ==  1

    return long_entries, short_entries, short_exits, long_exits, df

# =============================================================
# strategies/stochvol/strategy_v3.py
# =============================================================
# StochVol V3: Wider stoch periods + extended entry window
# =============================================================

import pandas as pd
import numpy as np
from strategies.stochvol.params_v3 import get_default_params


def get_entries_exits(df: pd.DataFrame, params: dict = None):
    p = {**get_default_params(), **(params or {})}

    # ── Resample 5m → 4h ─────────────────────────────────────
    df = df.resample("4h").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    df = df.copy()

    # ── Stochastic(21, 5, 5) ─────────────────────────────────
    k_period = p["stoch_k"]
    d_period = p["stoch_d"]
    smooth   = p["stoch_smooth"]

    lowest_low   = df["low"].rolling(k_period).min()
    highest_high = df["high"].rolling(k_period).max()
    raw_k        = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low + 1e-10)
    df["%K"]     = raw_k.rolling(smooth).mean()
    df["%D"]     = df["%K"].rolling(d_period).mean()

    # ── Cross detection ───────────────────────────────────────
    prev_k      = df["%K"].shift(1)
    prev_d      = df["%D"].shift(1)
    cross_above = (df["%K"] > df["%D"]) & (prev_k <= prev_d)
    cross_below = (df["%K"] < df["%D"]) & (prev_k >= prev_d)

    # ── Entry window: extend signal N candles after cross ─────
    # Long: fires on cross AND up to (window-1) candles after,
    #       only if K is still above D on that candle
    # Short: same logic reversed
    window = p.get("entry_window", 1)

    long_signal  = cross_above.copy()
    short_signal = cross_below.copy()

    for i in range(1, window):
        long_signal  = long_signal  | (cross_above.shift(i).fillna(False) & (df["%K"] > df["%D"]))
        short_signal = short_signal | (cross_below.shift(i).fillna(False) & (df["%K"] < df["%D"]))

    # Fresh cross always overrides window signal
    df["signal"] = 0
    df.loc[long_signal,  "signal"] =  1
    df.loc[short_signal, "signal"] = -1
    # If both fire on same candle (edge case), fresh cross wins
    df.loc[cross_below, "signal"] = -1
    df.loc[cross_above, "signal"] =  1

    # ── Volume features ───────────────────────────────────────
    vol_period      = p["vol_period"]
    df["vol_avg"]   = df["volume"].rolling(vol_period).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"].replace(0, 1e-10)

    # Block entries on low volume candles
    vol_min = p["vol_min_ratio"]
    df.loc[df["vol_ratio"] < vol_min, "signal"] = 0

    # ── ATR stop columns ──────────────────────────────────────
    atr_period = p["atr_period"]
    atr_mult   = p["atr_stop_mult"]
    hl         = df["high"] - df["low"]
    hc         = (df["high"] - df["close"].shift(1)).abs()
    lc         = (df["low"]  - df["close"].shift(1)).abs()
    tr         = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr        = tr.ewm(span=atr_period, adjust=False).mean()
    df["atr"]             = atr
    df["stop_loss_long"]  = df["close"] - atr * atr_mult
    df["stop_loss_short"] = df["close"] + atr * atr_mult

    # ── df.attrs — pass execution params to engine ────────────
    df.attrs["trail_trigger"]       = p["trail_trigger"]
    df.attrs["trail_offset"]        = p["trail_offset"]
    df.attrs["trail_tight_trigger"] = p["trail_tight_trigger"]
    df.attrs["trail_tight_offset"]  = p["trail_tight_offset"]
    df.attrs["use_atr_sizing"]      = True
    df.attrs["vol_dry_threshold"]   = p["vol_dry_threshold"]
    df.attrs["vol_dry_close_pct"]   = p["vol_dry_close_pct"]
    df.attrs["vol_size_min"]        = p["vol_size_min"]
    df.attrs["vol_size_max"]        = p["vol_size_max"]

    # ── Warmup removal ────────────────────────────────────────
    warmup = max(k_period + d_period + smooth, vol_period) + 5
    df     = df.iloc[warmup:].copy()

    long_entries  = df["signal"] == 1
    short_entries = pd.Series(False, index=df.index)
    long_exits    = df["signal"] == -1
    short_exits   = pd.Series(False, index=df.index)

    return long_entries, short_entries, short_exits, long_exits, df

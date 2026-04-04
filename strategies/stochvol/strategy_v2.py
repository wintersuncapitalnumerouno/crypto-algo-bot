# =============================================================
# strategies/stochvol/strategy_v2.py
# =============================================================
# StochVol V2: Same as V1 but with adaptive ATR stop.
#
# Key change vs V1:
#   - Normal volume (< 1.5x avg): ATR × 0.7 stop (tight)
#   - High volume  (≥ 1.5x avg): ATR × 1.0 stop (wider)
#
# Hypothesis: wider stop on high-volume entries gives the trade
# more room to breathe, reducing stop-outs on strong momentum
# moves. Smaller position size (due to wider stop) also reduces
# dollar drawdown on losing trades.
# =============================================================

import pandas as pd
import numpy as np
from strategies.stochvol.params_v2 import get_default_params


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

    # ── Stochastic(14, 3, 3) ─────────────────────────────────
    k_period = p["stoch_k"]
    d_period = p["stoch_d"]
    smooth   = p["stoch_smooth"]

    lowest_low   = df["low"].rolling(k_period).min()
    highest_high = df["high"].rolling(k_period).max()
    raw_k        = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low + 1e-10)
    df["%K"]     = raw_k.rolling(smooth).mean()
    df["%D"]     = df["%K"].rolling(d_period).mean()

    # Stochastic cross signals
    prev_k = df["%K"].shift(1)
    prev_d = df["%D"].shift(1)
    cross_above = (df["%K"] > df["%D"]) & (prev_k <= prev_d)
    cross_below = (df["%K"] < df["%D"]) & (prev_k >= prev_d)

    df["signal"] = 0
    df.loc[cross_above, "signal"] =  1
    df.loc[cross_below, "signal"] = -1

    # ── Volume features ───────────────────────────────────────
    vol_period      = p["vol_period"]
    df["vol_avg"]   = df["volume"].rolling(vol_period).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"].replace(0, 1e-10)

    # Block entries on low volume candles
    vol_min = p["vol_min_ratio"]
    df.loc[df["vol_ratio"] < vol_min, "signal"] = 0

    # ── ATR calculation ───────────────────────────────────────
    atr_period = p["atr_period"]
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift(1)).abs()
    lc  = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(span=atr_period, adjust=False).mean()
    df["atr"] = atr

    # ── Adaptive ATR stop ─────────────────────────────────────
    # KEY CHANGE VS V1:
    # High volume candles (vol_ratio >= vol_high_threshold) get wider stop
    # This gives strong momentum moves more room to breathe
    atr_mult_normal = p["atr_stop_mult"]          # 0.7x — normal volume
    atr_mult_high   = p["atr_stop_mult_high"]      # 1.0x — high volume
    vol_high_thresh = p["vol_high_threshold"]       # 1.5x avg volume

    is_high_vol = df["vol_ratio"] >= vol_high_thresh
    effective_mult = np.where(is_high_vol, atr_mult_high, atr_mult_normal)

    df["stop_loss_long"]  = df["close"] - atr * effective_mult
    df["stop_loss_short"] = df["close"] + atr * effective_mult

    # ── Verify adaptive stop is working ──────────────────────
    # Debug: check that high-vol candles have wider stops
    # high_vol_stops = (df["close"] - df["stop_loss_long"])[is_high_vol].mean()
    # norm_vol_stops = (df["close"] - df["stop_loss_long"])[~is_high_vol].mean()
    # print(f"High vol avg stop: {high_vol_stops:.4f}, Normal vol avg stop: {norm_vol_stops:.4f}")

    # ── df.attrs — pass execution params to engine ────────────
    df.attrs["trail_trigger"]       = p["trail_trigger"]
    df.attrs["trail_offset"]        = p["trail_offset"]
    df.attrs["trail_tight_trigger"] = p["trail_tight_trigger"]
    df.attrs["trail_tight_offset"]  = p["trail_tight_offset"]
    df.attrs["use_atr_sizing"]      = True   # use ATR stop for sizing
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

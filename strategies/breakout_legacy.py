# =============================================================
# strategies/breakout.py — Breakout / Volatility Strategy
# =============================================================
#
# THE IDEA:
#   Markets often consolidate in a range (bouncing between a
#   high and a low) before making a strong directional move.
#   When price BREAKS OUT of that range with strong volume,
#   it often continues in that direction — we ride that move.
#
#   Think of it like a coiled spring: the longer it compresses,
#   the stronger the explosion when it finally breaks.
#
# SIGNALS:
#   Entry Long  : Close > highest high of last N candles
#                 AND volume > average volume * factor
#   Entry Short : Close < lowest low  of last N candles
#                 AND volume > average volume * factor
#
#   Stop Loss   : 1x ATR below breakout level
#   Take Profit : 3x stop distance (3:1 Risk/Reward)
#
# WHY VOLUME?
#   A breakout WITHOUT volume is often a "fake breakout" that
#   quickly reverses. High volume confirms real conviction.
# =============================================================

import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config


# ─────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — same as in momentum.py"""
    high      = df["high"]
    low       = df["low"]
    close     = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def rolling_high(df: pd.DataFrame, period: int) -> pd.Series:
    """Highest high over the last N candles (excluding current candle)."""
    # shift(1) = look at PREVIOUS candles, not the current one
    # This prevents "lookahead bias" — a common backtest mistake
    return df["high"].shift(1).rolling(period).max()


def rolling_low(df: pd.DataFrame, period: int) -> pd.Series:
    """Lowest low over the last N candles (excluding current candle)."""
    return df["low"].shift(1).rolling(period).min()


def average_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Average volume over the last N candles."""
    return df["volume"].shift(1).rolling(period).mean()


def compute_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Add all breakout indicators to the dataframe."""
    df = df.copy()

    lookback   = params.get("lookback",   config.BREAKOUT["lookback"])
    atr_period = params.get("atr_period", config.BREAKOUT["atr_period"])
    vol_period = lookback  # Use same lookback for volume average

    df["atr"]        = atr(df, atr_period)
    df["range_high"] = rolling_high(df, lookback)  # Resistance level
    df["range_low"]  = rolling_low(df, lookback)   # Support level
    df["avg_volume"] = average_volume(df, vol_period)

    # Range width: how tight/wide is the current consolidation zone?
    df["range_width"] = df["range_high"] - df["range_low"]

    # Relative volume: current volume vs average (> 1 = above average)
    df["rel_volume"]  = df["volume"] / df["avg_volume"]

    return df


# ─────────────────────────────────────────────────────────────
# SIGNAL GENERATION
# ─────────────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Generate breakout entry signals.

    A LONG breakout = close > previous N-period high + high volume
    A SHORT breakout = close < previous N-period low  + high volume
    """
    if params is None:
        params = config.BREAKOUT

    df = compute_indicators(df, params)

    atr_mult   = params.get("atr_multiplier",  config.BREAKOUT["atr_multiplier"])
    vol_factor = params.get("volume_factor",   config.BREAKOUT["volume_factor"])
    stop_mult  = params.get("stop_atr_mult",   config.BREAKOUT["stop_atr_mult"])
    rr         = params.get("rr_ratio",        config.BREAKOUT["rr_ratio"])

    # ── Breakout Conditions ───────────────────────────────────

    # LONG breakout: close above the recent high
    # The atr_mult buffer helps avoid tiny "false" breakouts
    upside_breakout = (
        (df["close"] > df["range_high"] + df["atr"] * atr_mult) &
        (df["rel_volume"] >= vol_factor)   # Volume confirmation
    )

    # SHORT breakout: close below the recent low
    downside_breakout = (
        (df["close"] < df["range_low"] - df["atr"] * atr_mult) &
        (df["rel_volume"] >= vol_factor)   # Volume confirmation
    )

    # ── Signals ───────────────────────────────────────────────
    df["signal"] = 0
    df.loc[upside_breakout,   "signal"] = 1
    df.loc[downside_breakout, "signal"] = -1

    # ── Stop Loss & Take Profit ───────────────────────────────
    df["stop_distance"] = df["atr"] * stop_mult

    # Long trade stops
    df["stop_loss_long"]   = df["range_high"] - df["stop_distance"]  # just below breakout level
    df["take_profit_long"] = df["close"]     + df["stop_distance"] * rr

    # Short trade stops
    df["stop_loss_short"]   = df["range_low"] + df["stop_distance"]  # just above breakdown level
    df["take_profit_short"] = df["close"]     - df["stop_distance"] * rr

    # Warm up period: need enough candles for rolling calculations
    warmup = params.get("lookback", config.BREAKOUT["lookback"]) * 2
    df = df.iloc[warmup:]

    return df


# ─────────────────────────────────────────────────────────────
# ENTRY / EXIT LOGIC (used by the backtest engine)
# ─────────────────────────────────────────────────────────────

def get_entries_exits(df: pd.DataFrame, params: dict = None):
    """
    Returns boolean arrays for vectorbt backtesting.
    Same interface as momentum.py — makes the engine plug-and-play.
    """
    if params is None:
        params = config.BREAKOUT

    df = generate_signals(df, params)

    long_entries  = df["signal"] == 1
    short_entries = df["signal"] == -1
    long_exits    = short_entries
    short_exits   = long_entries

    return long_entries, long_exits, short_entries, short_exits, df


# ─────────────────────────────────────────────────────────────
# QUICK TEST: python strategies/breakout.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetch_data import load_candles

    coin     = "BTC"
    interval = config.PRIMARY_TIMEFRAME

    print(f"Loading {coin} {interval} data...")
    df = load_candles(coin, interval)

    print("Generating breakout signals...")
    df_signals = generate_signals(df)

    signals_only = df_signals[df_signals["signal"] != 0].copy()
    signals_only["direction"] = signals_only["signal"].map({1: "🟢 LONG", -1: "🔴 SHORT"})

    print(f"\n📊 {coin} {interval} — Breakout Signals (last 20):")
    cols = ["close", "range_high", "range_low", "rel_volume", "atr", "direction"]
    print(signals_only[cols].tail(20).to_string())

    total  = len(signals_only)
    longs  = (signals_only["signal"] == 1).sum()
    shorts = (signals_only["signal"] == -1).sum()

    print(f"\nTotal signals: {total} ({longs} long, {shorts} short)")
    print(f"Avg rel volume at signal: {signals_only['rel_volume'].mean():.2f}x")

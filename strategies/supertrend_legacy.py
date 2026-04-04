# =============================================================
# strategies/supertrend.py — SuperTrend Trend-Following Strategy
# =============================================================
#
# THE IDEA:
#   SuperTrend is a dynamic support/resistance indicator built
#   on ATR (volatility). Instead of fixed price levels, it
#   creates a "band" around price that ADAPTS to how volatile
#   the market is.
#
#   When price is ABOVE the SuperTrend line → uptrend → BUY
#   When price is BELOW the SuperTrend line → downtrend → SELL
#
#   Think of it like a moving floor/ceiling:
#     - In an uptrend, it acts as a rising support floor.
#       If price drops through the floor, trend has reversed.
#     - In a downtrend, it acts as a falling resistance ceiling.
#       If price breaks above the ceiling, trend has reversed.
#
# WHY THIS IS BETTER THAN EMA CROSSOVER:
#   EMA crossovers lag — they only react AFTER price has already
#   moved. SuperTrend is adaptive: in high-volatility markets
#   the band widens (fewer false signals), in calm markets it
#   tightens (catches moves earlier).
#
# THE MATH:
#   1. Calculate ATR over N periods (default: 10)
#   2. Compute Upper Band = (high+low)/2 + multiplier * ATR
#                           ↑ midpoint price ↑ volatility buffer
#   3. Compute Lower Band = (high+low)/2 - multiplier * ATR
#   4. Ratchet the bands:
#        - Lower band can only RISE (never drop below prior value)
#        - Upper band can only FALL (never rise above prior value)
#      This prevents the bands from immediately "snapping back"
#      on a single volatile candle — it creates hysteresis.
#   5. SuperTrend line = Upper Band (resistance) when in downtrend
#                      = Lower Band (support)    when in uptrend
#   6. Trend flips when close crosses the SuperTrend line.
#
# SIGNALS:
#   Entry Long  : SuperTrend flips from downtrend to uptrend
#                 (close crosses above the upper band)
#   Entry Short : SuperTrend flips from uptrend to downtrend
#                 (close crosses below the lower band)
#
#   Stop Loss   : SuperTrend band level (natural invalidation)
#                 + 0.5x ATR buffer (slippage protection)
#   Take Profit : 2x stop distance (2:1 Risk/Reward, configurable)
#
# REFERENCE: Chapter 6 of "Python for Algorithmic Trading"
#            The book uses this as its primary trend strategy.
#
# BEST PARAMETERS TO TRY FIRST (from book recommendation):
#   atr_period  : 10
#   multiplier  : 3.0
#   (Step 3 grid search will confirm optimal values for SOL 5m)
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
    """
    Average True Range — measures market volatility.

    True Range = max of:
      1. High - Low           (candle range)
      2. |High - Prev Close|  (gap-up scenario)
      3. |Low  - Prev Close|  (gap-down scenario)

    ATR = exponential average of True Range over N periods.
    High ATR = volatile (big candles), Low ATR = calm (small candles).
    """
    high       = df["high"]
    low        = df["low"]
    close      = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def compute_supertrend(df: pd.DataFrame, atr_period: int, multiplier: float) -> pd.DataFrame:
    """
    Compute the SuperTrend indicator and add all band columns to df.

    Adds these columns:
      atr          : Average True Range (volatility measure)
      upper_band   : resistance ceiling (ratcheted downward over time)
      lower_band   : support floor (ratcheted upward over time)
      supertrend   : the active SuperTrend line price level
      st_direction : +1 = uptrend, -1 = downtrend

    The "ratcheting" is what makes SuperTrend powerful:
      - The floor (lower_band) can only move UP — once price
        establishes a support level, that floor doesn't drop
        back down on the next candle. It holds until violated.
      - The ceiling (upper_band) can only move DOWN — resistance
        only tightens, never loosens, until a breakout occurs.

    This hysteresis prevents whipsaws from single noisy candles.
    """
    df = df.copy()

    # Step 1: Calculate ATR
    df["atr"] = atr(df, atr_period)

    # Step 2: Raw (un-ratcheted) bands
    # HL2 = midpoint of the candle high and low
    hl2 = (df["high"] + df["low"]) / 2

    raw_upper = hl2 + multiplier * df["atr"]   # ceiling above price
    raw_lower = hl2 - multiplier * df["atr"]   # floor below price

    # Step 3: Ratchet bands iteratively
    # Each candle's band depends on the PREVIOUS candle's band,
    # so we must loop — this cannot be vectorized.
    n = len(df)
    upper_band = np.zeros(n)
    lower_band = np.zeros(n)
    supertrend = np.zeros(n)
    direction  = np.zeros(n, dtype=int)   # +1 uptrend / -1 downtrend

    close          = df["close"].values
    raw_upper_vals = raw_upper.values
    raw_lower_vals = raw_lower.values

    # Seed the first candle — assume downtrend at start
    upper_band[0] = raw_upper_vals[0]
    lower_band[0] = raw_lower_vals[0]
    supertrend[0] = raw_upper_vals[0]
    direction[0]  = -1

    for i in range(1, n):
        # ── Ratchet lower_band upward only ────────────────────
        # The floor rises if: the new raw floor is higher
        # AND price was above the floor last candle (still valid).
        # If price was already below the floor, we reset it
        # (the support was broken, we start fresh).
        if raw_lower_vals[i] > lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
            lower_band[i] = raw_lower_vals[i]
        else:
            lower_band[i] = lower_band[i - 1]   # hold the higher floor

        # ── Ratchet upper_band downward only ──────────────────
        # The ceiling drops if: the new raw ceiling is lower
        # AND price was below the ceiling last candle (still valid).
        # If price was already above the ceiling, we reset it.
        if raw_upper_vals[i] < upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
            upper_band[i] = raw_upper_vals[i]
        else:
            upper_band[i] = upper_band[i - 1]   # hold the lower ceiling

        # ── Determine current trend direction ─────────────────
        if direction[i - 1] == 1:
            # We were in an UPTREND last candle.
            # Stay long unless price closes below the support floor.
            if close[i] < lower_band[i]:
                direction[i]  = -1               # trend reversal → downtrend
                supertrend[i] = upper_band[i]    # now tracking the ceiling
            else:
                direction[i]  = 1                # still uptrend
                supertrend[i] = lower_band[i]    # tracking the floor
        else:
            # We were in a DOWNTREND last candle.
            # Stay short unless price closes above the resistance ceiling.
            if close[i] > upper_band[i]:
                direction[i]  = 1                # trend reversal → uptrend
                supertrend[i] = lower_band[i]    # now tracking the floor
            else:
                direction[i]  = -1               # still downtrend
                supertrend[i] = upper_band[i]    # tracking the ceiling

    df["upper_band"]   = upper_band
    df["lower_band"]   = lower_band
    df["supertrend"]   = supertrend
    df["st_direction"] = direction

    return df


# ─────────────────────────────────────────────────────────────
# SIGNAL GENERATION
# ─────────────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Generate long/short entry signals from SuperTrend direction flips.

    A signal fires ONLY when the trend direction changes:
      +1 (long)  : st_direction flipped from -1 → +1
                   (price broke above upper band — momentum confirmed)
      -1 (short) : st_direction flipped from +1 → -1
                   (price broke below lower band — momentum confirmed)

    Stop and TP use the SuperTrend band as the natural level,
    plus a small ATR buffer to account for slippage.
    """
    if params is None:
        params = config.SUPERTREND

    atr_period = params.get("atr_period", config.SUPERTREND["atr_period"])
    multiplier = params.get("multiplier", config.SUPERTREND["multiplier"])
    rr         = params.get("rr_ratio",   config.SUPERTREND.get("rr_ratio", 2.0))

    df = compute_supertrend(df, atr_period, multiplier)

    # ── Detect direction flips ────────────────────────────────
    prev_direction = df["st_direction"].shift(1)

    # Long entry: direction just changed from DOWN to UP
    long_signal  = (df["st_direction"] == 1)  & (prev_direction == -1)

    # Short entry: direction just changed from UP to DOWN
    short_signal = (df["st_direction"] == -1) & (prev_direction == 1)

    # ── Signal column ─────────────────────────────────────────
    df["signal"] = 0
    df.loc[long_signal,  "signal"] = 1
    df.loc[short_signal, "signal"] = -1

    # ── Stop Loss & Take Profit ───────────────────────────────
    # The SuperTrend band is the natural invalidation level.
    # If we just went long because price broke above upper_band,
    # and price then falls back below lower_band, the trade is
    # invalidated. We use lower_band as the stop, minus a buffer.

    atr_buffer = df["atr"] * 0.5   # 0.5x ATR to avoid getting stopped by noise

    # Long trade: stop is the support floor (lower_band)
    df["stop_loss_long"]   = df["lower_band"] - atr_buffer
    df["take_profit_long"] = df["close"] + (df["close"] - df["stop_loss_long"]) * rr

    # Short trade: stop is the resistance ceiling (upper_band)
    df["stop_loss_short"]   = df["upper_band"] + atr_buffer
    df["take_profit_short"] = df["close"] - (df["stop_loss_short"] - df["close"]) * rr

    # Drop warm-up rows: SuperTrend needs ~2x atr_period candles to be reliable
    warmup = atr_period * 2
    df = df.iloc[warmup:]

    return df


# ─────────────────────────────────────────────────────────────
# ENTRY / EXIT LOGIC (used by backtest/engine.py)
# ─────────────────────────────────────────────────────────────

def get_entries_exits(df: pd.DataFrame, params: dict = None):
    """
    Returns boolean arrays for engine.py.
    Identical interface to momentum.py and breakout.py — plug-and-play.

    Returns:
      long_entries  : True on candles where we open a long position
      long_exits    : True on candles where we close a long position
      short_entries : True on candles where we open a short position
      short_exits   : True on candles where we close a short position
      df            : dataframe with all SuperTrend columns added
    """
    if params is None:
        params = config.SUPERTREND

    df = generate_signals(df, params)

    long_entries  = df["signal"] == 1
    short_entries = df["signal"] == -1

    # Exit on the opposite signal
    # (engine also enforces stop loss + take profit per candle)
    long_exits  = short_entries
    short_exits = long_entries

    return long_entries, long_exits, short_entries, short_exits, df


# ─────────────────────────────────────────────────────────────
# QUICK TEST: python strategies/supertrend.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data.fetch_data import load_candles

    coin     = "SOL"   # SOL 5m was the best performer in v1 — start here
    interval = config.PRIMARY_TIMEFRAME

    print(f"Loading {coin} {interval} data...")
    df = load_candles(coin, interval)

    print("Computing SuperTrend signals...")
    df_signals = generate_signals(df)

    signals_only = df_signals[df_signals["signal"] != 0].copy()
    signals_only["direction"] = signals_only["signal"].map({1: "🟢 LONG", -1: "🔴 SHORT"})

    print(f"\n📊 {coin} {interval} — SuperTrend Signals (last 20 signals):")
    cols = ["close", "supertrend", "lower_band", "upper_band", "atr", "direction"]
    print(signals_only[cols].tail(20).to_string())

    total  = len(signals_only)
    longs  = (signals_only["signal"] == 1).sum()
    shorts = (signals_only["signal"] == -1).sum()

    print(f"\nTotal signals : {total} ({longs} long, {shorts} short)")
    print(f"Signal rate   : {total / len(df_signals) * 100:.1f}% of candles")
    print(f"Avg ATR       : {signals_only['atr'].mean():.4f}")

    # Show current market state
    last = df_signals.iloc[-1]
    trend_str = "🟢 UPTREND" if last["st_direction"] == 1 else "🔴 DOWNTREND"
    print(f"\nCurrent state ({coin} {interval}): {trend_str}")
    print(f"  Close:        {last['close']:.4f}")
    print(f"  SuperTrend:   {last['supertrend']:.4f}")
    print(f"  Lower Band:   {last['lower_band']:.4f}")
    print(f"  Upper Band:   {last['upper_band']:.4f}")
    print(f"  ATR:          {last['atr']:.4f}")

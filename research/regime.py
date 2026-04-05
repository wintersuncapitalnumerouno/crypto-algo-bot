# =============================================================
# research/regime.py
# =============================================================
# Candle-by-candle regime classification.
#
# Three dimensions:
#   1. Trend   — up / down / range (EMA50/200 + ADX)
#   2. Vol     — low / high (ATR% rolling percentile)
#   3. Risk    — risk_on / risk_off / neutral (BTC trend + DVOL)
#
# First version uses trend + vol only (6 states).
# Risk backdrop can be layered on later.
#
# All functions take a 4h OHLCV DataFrame and return an
# aligned Series of string labels.
# =============================================================

import pandas as pd
import numpy as np


# ── Trend regime ─────────────────────────────────────────────

def classify_trend(df: pd.DataFrame,
                   ema_fast: int = 50,
                   ema_slow: int = 200,
                   adx_period: int = 14,
                   adx_trend_threshold: float = 20.0) -> pd.Series:
    """
    Classify each candle as 'up', 'down', or 'range'.

    up:    close > EMA50 AND EMA50 > EMA200 AND ADX > 20
    down:  close < EMA50 AND EMA50 < EMA200 AND ADX > 20
    range: everything else
    """
    d = df.copy()
    d["ema_fast"] = d["close"].ewm(span=ema_fast, adjust=False).mean()
    d["ema_slow"] = d["close"].ewm(span=ema_slow, adjust=False).mean()

    # ADX calculation
    d["adx"] = _compute_adx(d, adx_period)

    trend = pd.Series("range", index=d.index)

    up_mask = (
        (d["close"] > d["ema_fast"]) &
        (d["ema_fast"] > d["ema_slow"]) &
        (d["adx"] > adx_trend_threshold)
    )
    down_mask = (
        (d["close"] < d["ema_fast"]) &
        (d["ema_fast"] < d["ema_slow"]) &
        (d["adx"] > adx_trend_threshold)
    )

    trend[up_mask] = "up"
    trend[down_mask] = "down"

    return trend


def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ADX from OHLC data."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, 1e-10)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, 1e-10)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    adx = dx.ewm(span=period, adjust=False).mean()

    return adx


# ── Volatility regime ────────────────────────────────────────

def classify_vol(df: pd.DataFrame,
                 atr_period: int = 14,
                 lookback: int = 540,
                 low_pct: float = 40.0,
                 high_pct: float = 80.0) -> pd.Series:
    """
    Classify each candle as 'low_vol' or 'high_vol'.

    Uses ATR as % of price, with rolling percentile thresholds.
    lookback=540 candles at 4h = ~90 days.

    low_vol:  ATR% below low_pct percentile
    high_vol: ATR% above low_pct percentile
    """
    d = df.copy()

    hl = d["high"] - d["low"]
    hc = (d["high"] - d["close"].shift(1)).abs()
    lc = (d["low"] - d["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(span=atr_period, adjust=False).mean()

    atr_pct = atr / d["close"].replace(0, 1e-10) * 100

    rolling_threshold = atr_pct.rolling(lookback, min_periods=60).quantile(low_pct / 100)

    vol = pd.Series("high_vol", index=d.index)
    vol[atr_pct <= rolling_threshold] = "low_vol"

    return vol


# ── Risk backdrop (BTC-based) ────────────────────────────────

def classify_risk(btc_df: pd.DataFrame,
                  ema_period: int = 200,
                  dvol_df: pd.DataFrame = None,
                  dvol_threshold: float = 70.0) -> pd.Series:
    """
    Classify risk backdrop from BTC data.

    risk_on:   BTC close > EMA200 AND DVOL not elevated (or no DVOL data)
    risk_off:  BTC close < EMA200 OR DVOL elevated
    neutral:   mixed signals
    """
    d = btc_df.copy()
    d["ema200"] = d["close"].ewm(span=ema_period, adjust=False).mean()

    btc_above = d["close"] > d["ema200"]

    risk = pd.Series("neutral", index=d.index)
    risk[btc_above] = "risk_on"
    risk[~btc_above] = "risk_off"

    # Layer DVOL if available
    if dvol_df is not None and not dvol_df.empty:
        dvol_aligned = dvol_df.reindex(d.index, method="ffill")
        if "close" in dvol_aligned.columns:
            dvol_high = dvol_aligned["close"] > dvol_threshold
            # Elevated DVOL + BTC above EMA = neutral (mixed)
            risk[(btc_above) & (dvol_high)] = "neutral"
            # Elevated DVOL + BTC below EMA = risk_off
            risk[(~btc_above) & (dvol_high)] = "risk_off"

    return risk


# ── Combined regime labels ───────────────────────────────────

def build_regime_labels(df: pd.DataFrame,
                        btc_df: pd.DataFrame = None,
                        dvol_df: pd.DataFrame = None,
                        include_risk: bool = False) -> pd.DataFrame:
    """
    Build regime labels for each candle.

    Returns DataFrame with columns:
      - regime_trend: up / down / range
      - regime_vol:   low_vol / high_vol
      - regime_risk:  risk_on / risk_off / neutral (if include_risk)
      - regime:       combined label (e.g. 'up_lowvol')
    """
    trend = classify_trend(df)
    vol = classify_vol(df)

    result = pd.DataFrame({
        "regime_trend": trend,
        "regime_vol": vol,
    }, index=df.index)

    if include_risk and btc_df is not None:
        btc_4h = btc_df.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        risk = classify_risk(btc_4h, dvol_df=dvol_df)
        risk_aligned = risk.reindex(df.index, method="ffill")
        result["regime_risk"] = risk_aligned
        result["regime"] = (
            result["regime_trend"] + "_" +
            result["regime_vol"].str.replace("_vol", "") + "_" +
            result["regime_risk"]
        )
    else:
        result["regime"] = (
            result["regime_trend"] + "_" +
            result["regime_vol"].str.replace("_vol", "")
        )

    return result

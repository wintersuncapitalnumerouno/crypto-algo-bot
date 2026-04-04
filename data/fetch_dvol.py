# =============================================================
# data/fetch_dvol.py — Deribit DVOL Implied Volatility Fetcher
# =============================================================
#
# WHAT IS DVOL?
#   DVOL is Deribit's Bitcoin Volatility Index — the crypto
#   equivalent of the VIX. It measures the market's expectation
#   of how much BTC will move over the NEXT 30 days, expressed
#   as an annualised percentage.
#
#   It is calculated from real options order flow on Deribit,
#   which handles ~90% of all BTC options globally. This makes
#   it the most reliable implied volatility measure for crypto.
#
# WHAT THE NUMBER MEANS:
#   DVOL = 50  → market expects ~2.5% daily move  (calm)
#   DVOL = 70  → market expects ~3.5% daily move  (normal)
#   DVOL = 90  → market expects ~4.5% daily move  (elevated)
#   DVOL = 120 → market expects ~6.0% daily move  (high fear)
#
#   Rule of thumb from Deribit: daily expected move ≈ DVOL / 20
#
# WHY THIS MATTERS FOR YOUR STRATEGIES:
#   High DVOL → breakouts have real momentum behind them → trade
#   Low DVOL  → market is grinding sideways → fake breakouts abound
#
#   This is used as a REGIME FILTER in engine.py:
#     - If DVOL > threshold → allow breakout/supertrend trades
#     - If DVOL < threshold → reduce size or skip signal
#
# API DETAILS:
#   Endpoint : https://www.deribit.com/api/v2/public/get_volatility_index_data
#   Auth     : None required (public endpoint)
#   History  : Available from 2021-04-01
#   Resolution: 60 seconds minimum, we use 1h (3600s) for storage
#
# HOW TO RUN:
#   python data/fetch_dvol.py
#
# WORKFLOW:
#   fetch_data.py → fetch_dvol.py → validate_data.py → engine.py
# =============================================================

import os
import sys
import time
import requests
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

DERIBIT_URL    = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
DVOL_FILE      = os.path.join(config.DATA_DIR, "BTC_DVOL_1h.csv")
RESOLUTION_SEC = 3600          # 1 hour candles (3600 seconds)
LOOKBACK_DAYS  = 1800          # ~5 years — Deribit DVOL starts 2021-04-01
MAX_CANDLES    = 10_000        # Deribit returns max 10,000 per request

# ─────────────────────────────────────────────────────────────
# IV REGIME THRESHOLDS
# ─────────────────────────────────────────────────────────────
#
# These define what "low", "normal", and "high" volatility means.
# Based on BTC's historical DVOL distribution:
#   ~20th percentile ≈ 45
#   ~50th percentile ≈ 65
#   ~80th percentile ≈ 90
#
# Adjust these after you look at your downloaded data.

IV_LOW    = 45    # below this → calm market, skip breakouts
IV_NORMAL = 70    # 45–70     → normal, trade with standard size
IV_HIGH   = 90    # above 90  → elevated, breakouts likely real
IV_CRISIS = 120   # above 120 → extreme fear, reduce size


# ─────────────────────────────────────────────────────────────
# FETCH FUNCTIONS
# ─────────────────────────────────────────────────────────────

def to_ms(dt: datetime) -> int:
    """Convert datetime to milliseconds timestamp."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_dvol_chunk(start_ms: int, end_ms: int) -> pd.DataFrame:
    """
    Fetch one chunk of DVOL data from Deribit's public API.

    Deribit returns candles with:
      timestamp : milliseconds since epoch (UTC)
      open      : DVOL at start of period
      high      : highest DVOL in period
      low       : lowest DVOL in period
      close     : DVOL at end of period (most important)
    """
    params = {
        "currency":   "BTC",
        "resolution": RESOLUTION_SEC,
        "start_timestamp": start_ms,
        "end_timestamp":   end_ms,
    }

    try:
        r = requests.get(DERIBIT_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ❌ Deribit API error: {e}")
        return pd.DataFrame()

    if "result" not in data or "data" not in data["result"]:
        print(f"  ⚠️  Unexpected response: {data}")
        return pd.DataFrame()

    raw = data["result"]["data"]
    if not raw:
        return pd.DataFrame()

    # Deribit returns [timestamp, open, high, low, close] arrays
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()

    return df


def fetch_dvol(lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """
    Fetch full DVOL history by chunking requests.

    Deribit's API has a limit of 10,000 candles per request.
    At 1h resolution, that's ~416 days per request — plenty.
    We still chunk to be safe and to handle pagination.
    """
    end_dt   = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)

    print(f"  📥 BTC DVOL 1h from Deribit | {start_dt.date()} → {end_dt.date()}")

    all_chunks = []
    chunk_start = start_dt

    # Each chunk covers ~416 days at 1h, so usually just one request
    chunk_days = 40   # 40 days x 24h = 960 candles, safely under 1000 limit

    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(days=chunk_days), end_dt)

        df = fetch_dvol_chunk(to_ms(chunk_start), to_ms(chunk_end))

        if not df.empty:
            all_chunks.append(df)
            print(f"    ✓ {len(df):,} candles ({chunk_start.date()} → {chunk_end.date()})")
        else:
            print(f"    ⚠️  No data for {chunk_start.date()} → {chunk_end.date()}")

        chunk_start = chunk_end
        time.sleep(0.3)   # be polite to the API

    if not all_chunks:
        print("  ❌ No DVOL data received")
        return pd.DataFrame()

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    print(f"  ✅ {len(df):,} total DVOL candles")

    return df


# ─────────────────────────────────────────────────────────────
# ENRICHMENT — add regime and daily move columns
# ─────────────────────────────────────────────────────────────

def enrich_dvol(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived columns that make DVOL immediately useful
    for strategy filtering.

    Adds:
      daily_move_pct : expected 1-day BTC move (DVOL / 20)
      iv_regime      : "low" / "normal" / "high" / "crisis"
      iv_rank        : where current DVOL sits in 1-year range (0–100)
                       like VIX term structure position
    """
    df = df.copy()

    # Expected daily move (Deribit's own formula: DVOL / 20)
    df["daily_move_pct"] = df["close"] / 20.0

    # Regime label — tells strategies what mode the market is in
    conditions = [
        df["close"] >= IV_CRISIS,
        df["close"] >= IV_HIGH,
        df["close"] >= IV_NORMAL,
    ]
    choices = ["crisis", "high", "normal"]
    df["iv_regime"] = np.select(conditions, choices, default="low")

    # IV Rank (0–100): where is current DVOL in its 1-year range?
    # 100 = at the highest it's been in a year (extreme fear)
    # 0   = at the lowest it's been in a year (very calm)
    window = 365 * 24   # 1 year of hourly candles
    rolling_min = df["close"].rolling(window, min_periods=30).min()
    rolling_max = df["close"].rolling(window, min_periods=30).max()
    df["iv_rank"] = (
        (df["close"] - rolling_min) / (rolling_max - rolling_min) * 100
    ).round(1)

    return df


# ─────────────────────────────────────────────────────────────
# REGIME FILTER CLASS — used by engine.py
# ─────────────────────────────────────────────────────────────

class IVRegimeFilter:
    """
    Loads DVOL data and answers one question for the engine:
    "Is this a good time to take a breakout/supertrend trade?"

    Usage in engine.py:
        from data.fetch_dvol import IVRegimeFilter
        iv_filter = IVRegimeFilter()

        # Before taking a trade:
        if iv_filter.allow_trade(timestamp, strategy="Breakout"):
            # take the trade
    """

    def __init__(self, dvol_path: str = DVOL_FILE):
        self.df = None
        self._load(dvol_path)

    def _load(self, path: str):
        if not os.path.exists(path):
            print(f"  ⚠️  DVOL file not found: {path}")
            print(f"     Run: python data/fetch_dvol.py")
            return

        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        self.df = df
        print(f"  📊 DVOL loaded: {len(df):,} hourly candles")

    def get_dvol_at(self, timestamp: pd.Timestamp) -> float | None:
        """
        Get the most recent DVOL close value at or before a given timestamp.
        Uses forward-fill logic — if there's no exact match, use last known value.
        """
        if self.df is None:
            return None

        # Find the most recent DVOL candle at or before this timestamp
        available = self.df[self.df.index <= timestamp]
        if available.empty:
            return None

        return available.iloc[-1]["close"]

    def get_regime_at(self, timestamp: pd.Timestamp) -> str:
        """
        Return the IV regime at a given timestamp.
        Returns: "low", "normal", "high", "crisis", or "unknown"
        """
        dvol = self.get_dvol_at(timestamp)
        if dvol is None:
            return "unknown"

        if dvol >= IV_CRISIS:  return "crisis"
        if dvol >= IV_HIGH:    return "high"
        if dvol >= IV_NORMAL:  return "normal"
        return "low"

    def allow_trade(self, timestamp: pd.Timestamp, strategy: str = "any") -> bool:
        """
        Returns True if the IV regime permits taking a new trade.

        Rules by strategy type:
          Breakout / SuperTrend : need IV_NORMAL or higher
                                  (these strategies need real momentum)
          Momentum              : allow in all regimes
                                  (EMA crossover can work in any condition)
          any                   : allow in all regimes (default)

        Returns True if DVOL data is unavailable (fail open — don't
        block trades just because we couldn't load the file).
        """
        regime = self.get_regime_at(timestamp)

        if regime == "unknown":
            return True   # no data = don't block

        if strategy in ("Breakout", "SuperTrend"):
            # These need real volatility to work
            # Skip in low regime, trade in normal/high/crisis
            # (crisis we still trade but you'd reduce size manually)
            return regime != "low"

        # Momentum and everything else: trade in all regimes
        return True

    def summary(self) -> str:
        """Print a quick summary of current DVOL conditions."""
        if self.df is None:
            return "DVOL data not loaded"

        last = self.df.iloc[-1]
        dvol = last["close"]
        regime = last.get("iv_regime", "unknown")
        iv_rank = last.get("iv_rank", "?")
        daily_move = dvol / 20.0

        return (
            f"BTC DVOL: {dvol:.1f}  |  "
            f"Regime: {regime.upper()}  |  "
            f"IV Rank: {iv_rank:.0f}/100  |  "
            f"Expected daily move: ±{daily_move:.1f}%"
        )


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  📉 DVOL Fetcher — Deribit Implied Volatility Index")
    print("  No API key required (public endpoint)")
    print("=" * 60)

    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Fetch
    df = fetch_dvol(lookback_days=LOOKBACK_DAYS)

    if df.empty:
        print("\n❌ Failed to fetch DVOL data.")
        sys.exit(1)

    # Enrich with regime labels
    df = enrich_dvol(df)

    # Save
    df.to_csv(DVOL_FILE)
    print(f"\n  💾 Saved → {DVOL_FILE}")

    # Summary stats
    print("\n" + "=" * 60)
    print("  📊 DVOL Summary")
    print("=" * 60)
    print(f"  Period      : {df.index[0].date()} → {df.index[-1].date()}")
    print(f"  Candles     : {len(df):,} hourly")
    print(f"  DVOL range  : {df['close'].min():.1f} → {df['close'].max():.1f}")
    print(f"  DVOL mean   : {df['close'].mean():.1f}")
    print(f"  DVOL median : {df['close'].median():.1f}")

    # Regime distribution
    regime_pct = df["iv_regime"].value_counts(normalize=True) * 100
    print(f"\n  Regime distribution:")
    for regime in ["low", "normal", "high", "crisis"]:
        pct = regime_pct.get(regime, 0)
        bar = "█" * int(pct / 2)
        print(f"    {regime:<8}: {pct:5.1f}%  {bar}")

    # Current state
    print(f"\n  Current state:")
    iv = IVRegimeFilter(DVOL_FILE)
    print(f"    {iv.summary()}")

    # Practical implication
    last_dvol = df.iloc[-1]["close"]
    print(f"\n  Implication for your strategies:")
    if last_dvol < IV_LOW:
        print(f"    ⚠️  LOW volatility — breakouts likely fake, consider waiting")
    elif last_dvol < IV_NORMAL:
        print(f"    ✅ NORMAL volatility — trade with standard settings")
    elif last_dvol < IV_HIGH:
        print(f"    🟡 ELEVATED volatility — breakouts have real momentum")
    elif last_dvol < IV_CRISIS:
        print(f"    🟠 HIGH volatility — strong moves expected, widen stops")
    else:
        print(f"    🔴 CRISIS volatility — extreme moves, reduce position size")

    print(f"\n  Next: python backtest/engine.py")
    print("=" * 60)

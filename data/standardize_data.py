# =============================================================
# data/standardize_data.py — Data Standardization
# =============================================================
#
# WHY THIS EXISTS:
#   The book (Chapter 2) is clear: before any analysis or
#   backtesting, your time series index must be:
#     1. A proper DatetimeIndex (not strings or integers)
#     2. Timezone-aware and anchored to UTC
#     3. Free of duplicates
#     4. Free of NaNs (forward-filled where safe)
#     5. On a regular frequency (no random gaps)
#
#   Right now your data passes most of these, but there are
#   two silent problems:
#
#   PROBLEM 1 — TIMEZONE NAIVE INDEX IN CSVs
#     When pandas reads a CSV back, it sometimes strips the
#     timezone info from the index. Your load_candles() patches
#     this with utc=True, but standardizing at storage time
#     is cleaner and safer.
#
#   PROBLEM 2 — GAPS IN THE CANDLE SERIES
#     Crypto APIs occasionally skip candles (exchange hiccups,
#     rate limits, maintenance windows). Your validate_data.py
#     DETECTS these gaps but doesn't FIX them. Strategies that
#     compute rolling indicators (EMA, ATR) can produce wrong
#     values if the index has irregular spacing.
#
#   This script fixes both by:
#     - Enforcing a regular DatetimeIndex (asfreq)
#     - Forward-filling any missing candles (ffill with limit)
#     - Ensuring UTC timezone on every CSV
#     - Adding simple+compound returns columns (book Ch. 2)
#     - Reporting a before/after summary
#
# HOW TO RUN:
#   python data/standardize_data.py
#
# WHEN TO RUN:
#   After fetch_data.py and before backtest/engine.py
#   You only need to run this once per data download.
#   The corrected files overwrite the originals in place.
#
# BOOK REFERENCE:
#   Chapter 2 — "Analyze and Transform Financial Market Data
#   with pandas":
#     - tz_localize / tz_convert  (DatetimeIndex section)
#     - asfreq                    (Resampling section)
#     - ffill / bfill             (Addressing Missing Data)
#     - pct_change / log returns  (Calculating Asset Returns)
# =============================================================

import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ─────────────────────────────────────────────────────────────
# TIMEZONE CONFIGURATION
# ─────────────────────────────────────────────────────────────
#
# ALL data is stored and processed in UTC internally.
# This is the industry standard — every exchange API returns
# UTC timestamps, and mixing timezones causes subtle bugs.
#
# Your local timezone is only used for DISPLAY purposes
# (e.g., when you want to know "this signal fired at 3pm my time").
#
# Buenos Aires = UTC-3 (no daylight saving time)
# Change this if you move or want a different display zone.

LOCAL_TIMEZONE = "America/Argentina/Buenos_Aires"

# Timeframe string → pandas frequency offset string
# Used by asfreq() to enforce regular candle spacing
TF_TO_FREQ = {
    "1m":  "1min",
    "3m":  "3min",
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1D",
}

# Max number of consecutive missing candles to forward-fill.
# If a gap is larger than this, we leave NaNs (flag as corrupt).
# For 5m data: limit=3 means we'll fill up to 15 minutes of gaps.
FFILL_LIMIT = 3


# ─────────────────────────────────────────────────────────────
# CORE STANDARDIZATION FUNCTION
# ─────────────────────────────────────────────────────────────

def standardize(df: pd.DataFrame, timeframe: str) -> tuple[pd.DataFrame, dict]:
    """
    Apply all standardization steps to a single OHLCV dataframe.

    Following the book's Chapter 2 pipeline:
      1. Ensure DatetimeIndex is UTC-aware (tz_localize)
      2. Enforce regular frequency (asfreq) — fills structural gaps
      3. Forward-fill small missing candles (ffill with limit)
      4. Drop any remaining NaN rows (corrupt data)
      5. Remove duplicate timestamps
      6. Add simple returns column  (book: pct_change)
      7. Add compound returns column (book: np.log)

    Returns:
      df_clean : standardized dataframe
      report   : dict with before/after stats for display
    """
    report = {
        "rows_before":   len(df),
        "gaps_filled":   0,
        "rows_dropped":  0,
        "duplicates":    0,
        "tz_fixed":      False,
    }

    # ── Step 1: Ensure UTC-aware DatetimeIndex ────────────────
    # The book: "By default, DatetimeIndexes are timezone naive.
    # To localize, use tz_localize."
    if df.index.tz is None:
        # Index has no timezone info — attach UTC
        df.index = df.index.tz_localize("UTC")
        report["tz_fixed"] = True
    elif str(df.index.tz) != "UTC":
        # Index has a different timezone — convert to UTC
        df.index = df.index.tz_convert("UTC")
        report["tz_fixed"] = True

    # ── Step 2: Enforce regular frequency ────────────────────
    # The book: "resample alters the frequency."
    # asfreq() reindexes to a perfect grid — any missing candle
    # timestamps get added with NaN values.
    freq = TF_TO_FREQ.get(timeframe)
    if freq:
        rows_before_asfreq = len(df)
        df = df.asfreq(freq)   # this adds NaN rows for missing candles
        report["gaps_filled"] = len(df) - rows_before_asfreq

    # ── Step 3: Forward-fill small gaps ──────────────────────
    # The book: "Use ffill to propagate the last valid observation forward."
    # limit=FFILL_LIMIT means we only fill short gaps.
    # A 15-minute gap in 5m data gets filled. A 2-hour gap does not.
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    df[ohlcv_cols] = df[ohlcv_cols].ffill(limit=FFILL_LIMIT)

    # ── Step 4: Drop remaining NaNs (large gaps = corrupt) ───
    rows_before_drop = len(df)
    df = df.dropna(subset=ohlcv_cols)
    report["rows_dropped"] = rows_before_drop - len(df)

    # ── Step 5: Remove duplicate timestamps ──────────────────
    dupes = df.index.duplicated().sum()
    if dupes:
        df = df[~df.index.duplicated(keep="last")]
        report["duplicates"] = dupes

    # ── Step 6: Simple returns (book Ch. 2: pct_change) ──────
    # Simple return = (price_today - price_yesterday) / price_yesterday
    # Useful for performance attribution and Sharpe ratio calculation
    df["returns_simple"] = df["close"].pct_change()

    # ── Step 7: Compound (log) returns (book Ch. 2: np.log) ──
    # Log return = ln(price_today / price_yesterday)
    # Additive over time — preferred for statistical analysis
    df["returns_log"] = np.log(df["close"] / df["close"].shift(1))

    # Replace first-row NaN (no previous close to compare against)
    df["returns_simple"] = df["returns_simple"].fillna(0.0)
    df["returns_log"]    = df["returns_log"].fillna(0.0)

    report["rows_after"] = len(df)
    return df, report


def display_in_local_time(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """
    Return a copy of the dataframe with the index converted to
    your local timezone for human-readable display only.

    The book: "To convert from one timezone to another, use tz_convert."

    This does NOT affect the stored data — always UTC under the hood.
    """
    df_display = df.copy()
    df_display.index = df_display.index.tz_convert(LOCAL_TIMEZONE)
    return df_display.tail(n)


# ─────────────────────────────────────────────────────────────
# MAIN — process all coins and timeframes
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("  🔧 Data Standardizer — following book Chapter 2")
    print(f"  Storage timezone : UTC (industry standard)")
    print(f"  Display timezone : {LOCAL_TIMEZONE}")
    print("=" * 65)

    summary_rows = []

    for coin in config.COINS:
        for tf in config.TIMEFRAMES:
            csv_path = Path(config.DATA_DIR) / f"{coin}_{tf}.csv"

            if not csv_path.exists():
                summary_rows.append([
                    "❌ MISSING", coin, tf, "—", "—", "—", "run fetch_data.py"
                ])
                continue

            # Load raw CSV
            df = pd.read_csv(csv_path, index_col="timestamp", parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)

            # Standardize
            df_clean, report = standardize(df, tf)

            # Overwrite the CSV with clean version
            df_clean.to_csv(csv_path)

            # Build summary row
            changes = []
            if report["tz_fixed"]:       changes.append("tz fixed")
            if report["gaps_filled"] > 0: changes.append(f"{report['gaps_filled']} gaps filled")
            if report["rows_dropped"] > 0: changes.append(f"{report['rows_dropped']} rows dropped")
            if report["duplicates"] > 0:  changes.append(f"{report['duplicates']} dupes removed")
            status = "✅ CLEAN" if not changes else "🔧 FIXED"
            note   = ", ".join(changes) if changes else "already clean"

            summary_rows.append([
                status, coin, tf,
                f"{report['rows_before']:,}",
                f"{report['rows_after']:,}",
                note,
            ])

            # Show last 3 candles in local time (for sanity check)
            print(f"\n  {coin} {tf} — last 3 candles in {LOCAL_TIMEZONE}:")
            local_preview = display_in_local_time(df_clean, n=3)
            print(local_preview[["open", "high", "low", "close", "volume"]].to_string())

    # Print summary table
    print("\n" + "=" * 65)
    print("  📋 Standardization Summary")
    print("=" * 65)
    print(tabulate(
        summary_rows,
        headers=["Status", "Coin", "TF", "Rows Before", "Rows After", "Changes"],
        tablefmt="rounded_outline",
    ))

    print(f"""
📌 Key points:
   • All data is stored in UTC — this never changes
   • Use display_in_local_time() in your analysis scripts
     to see candle times in {LOCAL_TIMEZONE}
   • Returns columns added: returns_simple, returns_log
   • Re-run this any time you refresh your data

  Next: python backtest/engine.py
""")

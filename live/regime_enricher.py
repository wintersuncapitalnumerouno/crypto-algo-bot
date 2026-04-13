#!/usr/bin/env python3
"""
regime_enricher.py — Enrich trades_master.csv with DVOL and VIX at entry time.

Reads:  live/trades_master.csv        (append-only, never modified)
        data/candles/BTC_DVOL_1h.csv  (hourly DVOL)
        data/candles/macro_1h.csv     (hourly VIX)

Writes: live/trades_master_enriched.csv  (full copy + dvol_at_entry, vix_at_entry)

Run on demand or via cron. No production dependencies.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER_CSV    = ROOT / "live" / "trades_master.csv"
DVOL_CSV      = ROOT / "data" / "candles" / "BTC_DVOL_1h.csv"
MACRO_CSV     = ROOT / "data" / "candles" / "macro_1h.csv"
ENRICHED_CSV  = ROOT / "live" / "trades_master_enriched.csv"


def load_dvol() -> pd.Series:
    """Load DVOL close prices indexed by hourly timestamp."""
    df = pd.read_csv(DVOL_CSV, parse_dates=["timestamp"], index_col="timestamp")
    return df["close"].sort_index()


def load_vix() -> pd.Series:
    """Load VIX close prices indexed by hourly timestamp."""
    df = pd.read_csv(MACRO_CSV, parse_dates=[0], index_col=0)
    return df["VIX_close"].sort_index()


def enrich():
    trades = pd.read_csv(MASTER_CSV)
    if trades.empty:
        print("No trades to enrich.")
        return

    dvol = load_dvol()
    vix  = load_vix()

    entry_times = pd.to_datetime(trades["entry_time"], utc=True)

    # Floor to nearest hour to match 1h candle index
    entry_hours = entry_times.dt.floor("h")

    # asof lookup: find latest available value <= entry hour
    trades["dvol_at_entry"] = entry_hours.map(
        lambda t: dvol.asof(t) if t >= dvol.index[0] else None
    )
    trades["vix_at_entry"] = entry_hours.map(
        lambda t: vix.asof(t) if t >= vix.index[0] else None
    )

    trades.to_csv(ENRICHED_CSV, index=False)
    n = len(trades)
    dvol_filled = trades["dvol_at_entry"].notna().sum()
    vix_filled  = trades["vix_at_entry"].notna().sum()
    print(f"Enriched {n} trades -> {ENRICHED_CSV}")
    print(f"  DVOL filled: {dvol_filled}/{n}")
    print(f"  VIX  filled: {vix_filled}/{n}")


if __name__ == "__main__":
    enrich()

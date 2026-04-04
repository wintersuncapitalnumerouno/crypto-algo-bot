# =============================================================
# data/fetch_funding.py — Historical funding rates
# =============================================================
#
# WHAT IS FUNDING RATE?
#   Perpetual futures don't expire, so exchanges use a funding
#   mechanism to keep the perp price anchored to spot.
#   Every 8 hours, longs pay shorts (or vice versa).
#
#   Positive funding → longs pay shorts → market is overleveraged long
#   Negative funding → shorts pay longs → market is overleveraged short
#
# WHY WE NEED IT:
#   High positive funding = crowded long = contrarian SHORT signal
#   High negative funding = crowded short = contrarian LONG signal
#   Neutral funding = healthy market = trend signals more reliable
#
# SOURCES:
#   Binance: /fapi/v1/fundingRate  — history from 2019, 8h intervals
#   Hyperliquid: /info fundingHistory — from Aug 2024, 1h intervals
#
# OUTPUT:
#   data/candles/{COIN}_funding_8h.csv   ← Binance (full history)
#   data/candles/{COIN}_funding_1h.csv   ← Hyperliquid (recent)
#
# COLUMNS:
#   timestamp, funding_rate, funding_rate_annualized
#
# USAGE:
#   python data/fetch_funding.py
# =============================================================

import sys, os, time, requests
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

BINANCE_FUNDING_URL  = "https://fapi.binance.com/fapi/v1/fundingRate"
HL_API_URL           = config.HL_API_URL

# Binance symbol map
BINANCE_SYMBOLS = {
    "BTC":  "BTCUSDT",
    "SOL":  "SOLUSDT",
    "LINK": "LINKUSDT",
    "HYPE": None,   # not on Binance futures
}

# Hyperliquid symbol map
HL_SYMBOLS = {
    "BTC":  "BTC",
    "SOL":  "SOL",
    "LINK": "LINK",
    "HYPE": "HYPE",
}


# -------------------------------------------------------------
# Binance — 8h funding history
# -------------------------------------------------------------

def fetch_binance_funding(coin: str) -> pd.DataFrame | None:
    symbol = BINANCE_SYMBOLS.get(coin)
    if not symbol:
        print(f"  ⚠️  {coin}: not available on Binance futures, skipping.")
        return None

    print(f"  📥  Binance funding: {coin} ({symbol}) ...")

    all_rows = []
    # Start from 2019-09-01 (Binance perps launched)
    start_ms = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
    limit    = 1000

    while True:
        try:
            resp = requests.get(BINANCE_FUNDING_URL, params={
                "symbol":    symbol,
                "startTime": start_ms,
                "limit":     limit,
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ❌  {coin}: Binance request failed — {e}")
            break

        if not data:
            break

        all_rows.extend(data)

        if len(data) < limit:
            break   # reached the end

        # Next batch starts after last timestamp
        start_ms = data[-1]["fundingTime"] + 1
        time.sleep(0.3)

    if not all_rows:
        print(f"  ⚠️  {coin}: no Binance funding data")
        return None

    df = pd.DataFrame(all_rows)
    df["timestamp"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    # Annualized: 8h rate × 3 × 365
    df["funding_rate_annualized"] = df["funding_rate"] * 3 * 365 * 100
    df = df[["timestamp", "funding_rate", "funding_rate_annualized"]]
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]

    print(f"  ✅  {coin} Binance: {len(df):,} rows  "
          f"({str(df.index[0])[:10]} → {str(df.index[-1])[:10]})")
    return df


# -------------------------------------------------------------
# Hyperliquid — 1h funding history
# -------------------------------------------------------------

def fetch_hl_funding(coin: str) -> pd.DataFrame | None:
    hl_symbol = HL_SYMBOLS.get(coin)
    if not hl_symbol:
        return None

    print(f"  📥  Hyperliquid funding: {coin} ...")

    all_rows = []
    # HL funding started Aug 2024
    start_ms = int(datetime(2024, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Fetch in 30-day chunks (HL limit)
    chunk_ms = 30 * 24 * 60 * 60 * 1000
    end_ms   = min(start_ms + chunk_ms, now_ms)

    while start_ms < now_ms:
        try:
            resp = requests.post(HL_API_URL, json={
                "type":      "fundingHistory",
                "coin":      hl_symbol,
                "startTime": start_ms,
                "endTime":   end_ms,
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ❌  {coin}: HL request failed — {e}")
            break

        if data:
            all_rows.extend(data)

        start_ms = end_ms + 1
        end_ms   = min(start_ms + chunk_ms, now_ms)
        time.sleep(0.2)

    if not all_rows:
        print(f"  ⚠️  {coin}: no Hyperliquid funding data")
        return None

    df = pd.DataFrame(all_rows)
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    df["funding_rate_annualized"] = df["funding_rate"] * 24 * 365 * 100  # 1h rate
    df = df[["timestamp", "funding_rate", "funding_rate_annualized"]]
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]

    print(f"  ✅  {coin} Hyperliquid: {len(df):,} rows  "
          f"({str(df.index[0])[:10]} → {str(df.index[-1])[:10]})")
    return df


# -------------------------------------------------------------
# Save
# -------------------------------------------------------------

def save_funding(coin: str, df: pd.DataFrame, source: str):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    freq     = "8h" if source == "binance" else "1h"
    out_path = os.path.join(config.DATA_DIR, f"{coin}_funding_{freq}.csv")
    df.to_csv(out_path)
    print(f"  💾  Saved → {out_path}  ({len(df):,} rows)")


# -------------------------------------------------------------
# Summary stats — useful to know thresholds for regime filter
# -------------------------------------------------------------

def print_funding_stats(coin: str, df: pd.DataFrame):
    fr = df["funding_rate"] * 100  # in %
    print(f"\n  📊  {coin} funding stats:")
    print(f"      Mean   : {fr.mean():.4f}%")
    print(f"      Median : {fr.median():.4f}%")
    print(f"      Std    : {fr.std():.4f}%")
    print(f"      Min    : {fr.min():.4f}%")
    print(f"      Max    : {fr.max():.4f}%")
    print(f"      >0.05% : {(fr > 0.05).mean()*100:.1f}% of time  ← crowded long")
    print(f"      <-0.01%: {(fr < -0.01).mean()*100:.1f}% of time ← crowded short")


# -------------------------------------------------------------
# Main
# -------------------------------------------------------------

if __name__ == "__main__":
    coins = [c for c in config.COINS]

    print("=" * 60)
    print("  💸  Funding Rate Fetcher")
    print(f"  Coins  : {', '.join(coins)}")
    print(f"  Sources: Binance (8h, full history) + Hyperliquid (1h, Aug 2024+)")
    print("=" * 60 + "\n")

    for coin in coins:
        print(f"\n── {coin} ─────────────────────────────────────")

        # Binance 8h
        df_bn = fetch_binance_funding(coin)
        if df_bn is not None:
            save_funding(coin, df_bn, "binance")
            print_funding_stats(coin, df_bn)

        # Hyperliquid 1h
        df_hl = fetch_hl_funding(coin)
        if df_hl is not None:
            save_funding(coin, df_hl, "hyperliquid")

    print("\n" + "=" * 60)
    print("  ✅  Done!")
    print("  Output files:")
    for coin in coins:
        print(f"    data/candles/{coin}_funding_8h.csv   ← Binance")
        print(f"    data/candles/{coin}_funding_1h.csv   ← Hyperliquid")
    print("\n  Next: python backtest/engine.py")
    print("=" * 60)

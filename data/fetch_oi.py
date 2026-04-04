# =============================================================
# fetch_oi.py — Historical Open Interest (Binance + Hyperliquid)
# =============================================================
#
# WHAT IS OPEN INTEREST?
#   OI = total number of outstanding derivative contracts
#   that have not been settled. Unlike volume (which resets
#   daily), OI accumulates — it tells you how much money is
#   CURRENTLY committed to positions.
#
# WHY IT MATTERS:
#   OI ↑ + Price ↑ → new longs opening → trend confirmation
#   OI ↑ + Price ↓ → new shorts opening → bearish conviction
#   OI ↓ + Price ↑ → short squeeze → unstable, likely reversal
#   OI ↓ + Price ↓ → liquidations/capitulation → wait for bottom
#
# TWO SOURCES (intentional):
#   Binance  → CEX/institutional positioning (BTC/SOL/LINK)
#   Hyperliquid → on-chain degen positioning (all coins)
#   Divergence between them = actionable signal
#
# BINANCE API LIMITS:
#   Endpoint : /futures/data/openInterestHist
#   Max per request : 500 candles
#   Max history     : 30 days per request window
#   Available from  : ~2020 for BTC, varies per coin
#   Periods: 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d
#
# HYPERLIQUID API:
#   OI available from Nov 2024 for all coins
#   Fetched via metaAndAssetCtxs (snapshot, not history)
#   For historical HL OI we use candleSnapshot with OI field
#
# OUTPUT FILES:
#   data/candles/BTC_OI_1h.csv
#   data/candles/SOL_OI_1h.csv
#   data/candles/LINK_OI_1h.csv
#   data/candles/HYPE_OI_1h.csv
#
# Usage:
#   python data/fetch_oi.py
# =============================================================

import os, sys, time, requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# -------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------

BINANCE_OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"
HL_URL         = "https://api.hyperliquid.xyz/info"
PERIOD         = "1h"
CANDLES_LIMIT  = 500   # Binance max per request

BINANCE_COINS = {
    "BTC":  "BTCUSDT",
    "SOL":  "SOLUSDT",
    "LINK": "LINKUSDT",
}

HL_COINS = ["BTC", "SOL", "LINK", "HYPE"]

# Per-coin start dates — match our candle history
COIN_STARTS = {
    "BTC":  "2020-07-01",   # Binance OI history starts ~mid 2020
    "SOL":  "2021-01-01",   # SOL perp launched late 2020
    "LINK": "2020-07-01",
    "HYPE": "2024-11-01",   # HL only
}

# -------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------

def to_ms(dt): return int(dt.timestamp() * 1000)
def from_ms(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

def out_path(coin):
    return os.path.join(config.DATA_DIR, f"{coin}_OI_1h.csv")

# -------------------------------------------------------------
# BINANCE OI
# -------------------------------------------------------------

def fetch_binance_oi_chunk(symbol, start_ms, end_ms):
    params = {
        "symbol":    symbol,
        "period":    PERIOD,
        "limit":     CANDLES_LIMIT,
        "startTime": start_ms,
        "endTime":   end_ms,
    }
    try:
        r = requests.get(BINANCE_OI_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data or isinstance(data, dict):
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.rename(columns={
            "sumOpenInterest":      "oi_contracts",
            "sumOpenInterestValue": "oi_usd",
        })
        df["oi_contracts"] = df["oi_contracts"].astype(float)
        df["oi_usd"]       = df["oi_usd"].astype(float)
        df = df[["timestamp", "oi_contracts", "oi_usd"]].set_index("timestamp")
        return df
    except Exception as e:
        print(f"    ⚠️  Binance OI error: {e}")
        return pd.DataFrame()


def fetch_binance_oi(coin):
    symbol   = BINANCE_COINS[coin]
    start_dt = datetime.strptime(COIN_STARTS[coin], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt   = datetime.now(tz=timezone.utc)

    print(f"  📥  {coin} OI from Binance | {start_dt.date()} → {end_dt.date()}")

    all_chunks = []
    chunk_start = start_dt

    # 500 candles x 1h = ~20 days per chunk
    chunk_delta = timedelta(hours=CANDLES_LIMIT)

    while chunk_start < end_dt:
        chunk_end = min(chunk_start + chunk_delta, end_dt)
        df = fetch_binance_oi_chunk(symbol, to_ms(chunk_start), to_ms(chunk_end))

        if not df.empty:
            all_chunks.append(df)

        chunk_start = chunk_end
        time.sleep(0.15)   # stay under rate limits

    if not all_chunks:
        print(f"  ⚠️  No Binance OI data for {coin}")
        return pd.DataFrame()

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.columns = [f"binance_{c}" for c in df.columns]
    print(f"  ✅  {coin} Binance OI: {len(df):,} candles  ({str(df.index[0])[:10]} → {str(df.index[-1])[:10]})")
    return df


# -------------------------------------------------------------
# HYPERLIQUID OI — historical via candleSnapshot
# -------------------------------------------------------------

def fetch_hl_oi(coin):
    """
    Hyperliquid candleSnapshot includes OI field.
    History available from ~Nov 2024.
    We fetch in 7-day chunks (same as fetch_data.py).
    """
    start_dt = datetime(2024, 11, 1, tzinfo=timezone.utc)
    end_dt   = datetime.now(tz=timezone.utc)

    print(f"  📥  {coin} OI from Hyperliquid | {start_dt.date()} → {end_dt.date()}")

    all_chunks = []
    chunk_start = start_dt

    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(days=7), end_dt)
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin":      coin,
                "interval":  "1h",
                "startTime": to_ms(chunk_start),
                "endTime":   to_ms(chunk_end),
            }
        }
        try:
            r = requests.post(HL_URL, json=payload, timeout=15)
            r.raise_for_status()
            raw = r.json()
            if raw:
                records = []
                for c in raw:
                    records.append({
                        "timestamp": from_ms(c["t"]),
                        "hl_oi":     float(c.get("oi", 0)),
                    })
                chunk_df = pd.DataFrame(records).set_index("timestamp")
                all_chunks.append(chunk_df)
        except Exception as e:
            print(f"    ⚠️  HL OI error: {e}")

        chunk_start = chunk_end
        time.sleep(0.2)

    if not all_chunks:
        print(f"  ⚠️  No Hyperliquid OI data for {coin}")
        return pd.DataFrame()

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    print(f"  ✅  {coin} HL OI: {len(df):,} candles  ({str(df.index[0])[:10]} → {str(df.index[-1])[:10]})")
    return df


# -------------------------------------------------------------
# COMBINE + ENRICH
# -------------------------------------------------------------

def enrich_oi(df, coin):
    """
    Add derived columns useful for strategy signals:
      oi_change_pct : % change in OI vs previous candle
      oi_zscore     : z-score of OI over rolling 30d window
                      (how unusual is current OI level?)
    """
    df = df.copy()

    # OI change %
    if "binance_oi_usd" in df.columns:
        df["oi_change_pct"] = df["binance_oi_usd"].pct_change() * 100
        # 30-day rolling z-score
        window = 30 * 24
        roll_mean = df["binance_oi_usd"].rolling(window, min_periods=24).mean()
        roll_std  = df["binance_oi_usd"].rolling(window, min_periods=24).std()
        df["oi_zscore"] = (df["binance_oi_usd"] - roll_mean) / roll_std

    return df


# -------------------------------------------------------------
# MAIN
# -------------------------------------------------------------

def fetch_and_save(coin):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    frames = []

    # Binance (BTC/SOL/LINK)
    if coin in BINANCE_COINS:
        bn_df = fetch_binance_oi(coin)
        if not bn_df.empty:
            frames.append(bn_df)

    # Hyperliquid (all coins)
    if coin in HL_COINS:
        hl_df = fetch_hl_oi(coin)
        if not hl_df.empty:
            frames.append(hl_df)

    if not frames:
        print(f"  ❌  No OI data for {coin}")
        return

    # Merge Binance + HL on timestamp
    if len(frames) == 1:
        combined = frames[0]
    else:
        combined = frames[0].join(frames[1], how="outer")

    combined = combined.sort_index()
    combined = enrich_oi(combined, coin)

    path = out_path(coin)
    combined.to_csv(path)
    print(f"  💾  Saved → {path}  ({len(combined):,} rows)\n")


if __name__ == "__main__":
    print("=" * 60)
    print("  📊  Open Interest Fetcher")
    print(f"  Sources  : Binance (CEX) + Hyperliquid (on-chain)")
    print(f"  Timeframe: {PERIOD}")
    print(f"  Coins    : {', '.join(BINANCE_COINS)} + HYPE (HL only)")
    print("=" * 60 + "\n")

    coins = list(BINANCE_COINS.keys()) + ["HYPE"]

    for coin in coins:
        print(f"── {coin} {'─'*40}")
        fetch_and_save(coin)

    print("=" * 60)
    print("  ✅  Done!")
    print("\n  Files saved:")
    for coin in coins:
        p = out_path(coin)
        if os.path.exists(p):
            df = pd.read_csv(p)
            print(f"    {coin}_OI_1h.csv  —  {len(df):,} rows")
    print("\n  Next: python data/fetch_funding.py")
    print("=" * 60)

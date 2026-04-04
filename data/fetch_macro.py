# =============================================================
# fetch_macro.py — Fetch macro/tradfi data (mixed provider)
# =============================================================
#
# Provider per instrument:
#   VIX    — yfinance ^VIX      (IBKR can't serve 1h history)
#   SPX    — IBKR IND/CBOE      (real-time, full history) ✅
#   DXY    — yfinance DX-Y.NYB  (IBKR front month only ~10 months)
#   US10Y  — yfinance ^TNX      (IBKR ZN exchange string issues)
#   GLD    — IBKR STK/ARCA      (real-time, full history) ✅
#
# yfinance strategy:
#   daily 1d  → resampled to 1h  (2019 → 60 days ago)
#   intraday 1h                  (last 60 days, real candles)
#   merged → deduplicated → saved
#
# Output:
#   data/candles/macro_1h.csv
#
# Usage:
#   python data/fetch_macro.py
# =============================================================

import sys, os, time
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# Instruments to fetch via yfinance (IBKR can't serve these reliably)
YF_SYMBOLS = {
    "VIX":   "^VIX",
    "DXY":   "DX-Y.NYB",
    "US10Y": "^TNX",
}

# Instruments to fetch via IBKR (real-time, full history)
IBKR_SYMBOLS = {
    "SPX": {"symbol": "SPX", "secType": "IND", "exchange": "CBOE", "currency": "USD"},
    "GLD": {"symbol": "GLD", "secType": "STK", "exchange": "ARCA", "currency": "USD"},
}


# -------------------------------------------------------------
# yfinance fetcher — daily resampled + real 1h last 60 days
# -------------------------------------------------------------

def fetch_yfinance_instrument(name, yf_symbol):
    try:
        import yfinance as yf
    except ImportError:
        print("❌  yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    print(f"  📥  Fetching {name} via yfinance ({yf_symbol}) ...")
    try:
        daily = yf.download(yf_symbol, start="2019-01-01", interval="1d", progress=False)
        intra = yf.download(yf_symbol, period="60d", interval="1h", progress=False)

        if daily.empty:
            print(f"  ⚠️  {name}: no daily data from yfinance")
            return None

        daily.index = pd.to_datetime(daily.index, utc=True)

        # Flatten multi-level columns (yfinance v0.2+)
        if isinstance(daily.columns, pd.MultiIndex):
            daily.columns = daily.columns.get_level_values(0)
        if not intra.empty and isinstance(intra.columns, pd.MultiIndex):
            intra.columns = intra.columns.get_level_values(0)

        # Resample daily → 1h
        daily_close = daily[["Close"]].copy()
        daily_close.columns = ["close"]
        daily_1h = daily_close.resample("1h").ffill()
        daily_1h["open"]   = daily_1h["close"]
        daily_1h["high"]   = daily_1h["close"]
        daily_1h["low"]    = daily_1h["close"]
        daily_1h["volume"] = 0

        if not intra.empty:
            intra.index = pd.to_datetime(intra.index, utc=True)
            intra_clean = intra[["Open", "High", "Low", "Close", "Volume"]].copy()
            intra_clean.columns = ["open", "high", "low", "close", "volume"]
            combined = pd.concat([daily_1h, intra_clean])
        else:
            combined = daily_1h

        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        combined.columns = [f"{name}_{c}" for c in combined.columns]

        print(f"  ✅  {name}: {len(combined):,} bars  "
              f"({str(combined.index[0])[:10]} → {str(combined.index[-1])[:10]})\n")
        return combined

    except Exception as e:
        print(f"  ⚠️  {name}: yfinance error — {e}")
        return None


# -------------------------------------------------------------
# IBKR fetcher — real-time 1h, 7 x 1Y chunks
# -------------------------------------------------------------

def fetch_ibkr_instruments():
    try:
        from ib_insync import IB, Index, Stock, util
    except ImportError:
        print("❌  ib_insync not installed.")
        sys.exit(1)

    print(f"🔌  Connecting to IB Gateway at {config.IBKR_HOST}:{config.IBKR_PORT} ...")
    ib = IB()
    try:
        ib.connect(config.IBKR_HOST, config.IBKR_PORT, clientId=config.IBKR_CLIENT_ID)
    except Exception as e:
        print(f"❌  Connection failed: {e}\n"
              "    Make sure IB Gateway is running (port 4001, Read-Only unchecked).")
        return {}
    print("✅  Connected!\n")

    frames = {}

    for name, cfg in IBKR_SYMBOLS.items():
        print(f"  📥  Fetching {name} ({cfg['secType']}) via IBKR ...")
        try:
            if cfg["secType"] == "IND":
                contract = Index(cfg["symbol"], cfg["exchange"], cfg["currency"])
            else:
                contract = Stock(cfg["symbol"], cfg["exchange"], cfg["currency"])
            ib.qualifyContracts(contract)
        except Exception as e:
            print(f"  ⚠️  Could not qualify {name}: {e}")
            continue

        all_bars = []
        end_dt   = ""

        for i in range(7):
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime=end_dt,
                    durationStr="1 Y",
                    barSizeSetting="1 hour",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    all_bars = list(bars) + all_bars
                    end_dt   = bars[0].date
                    print(f"    chunk {i+1}/7: {len(bars)} bars, earliest: {bars[0].date}")
                else:
                    print(f"    chunk {i+1}/7: no data (reached history limit)")
                    break
                time.sleep(1)
            except Exception as e:
                print(f"    chunk {i+1}/7: error — {e}")
                break

        if not all_bars:
            print(f"  ⚠️  No data received for {name}\n")
            continue

        df = util.df(all_bars)[["date", "open", "high", "low", "close", "volume"]]
        df = df.rename(columns={"date": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.columns = [f"{name}_{c}" for c in df.columns]
        frames[name] = df
        print(f"  ✅  {name}: {len(df):,} bars  "
              f"({str(df.index[0])[:10]} → {str(df.index[-1])[:10]})\n")

    ib.disconnect()
    print("🔌  Disconnected from IB Gateway\n")
    return frames


# -------------------------------------------------------------
# Save combined
# -------------------------------------------------------------

def save_macro(frames):
    if not frames:
        print("❌  No macro data to save.")
        return

    os.makedirs(config.DATA_DIR, exist_ok=True)
    out_path = os.path.join(config.DATA_DIR, "macro_1h.csv")

    combined = pd.concat(frames.values(), axis=1, join="outer").sort_index()
    combined = combined.ffill(limit=3)
    combined.to_csv(out_path)

    print(f"💾  Saved → {out_path}")
    print(f"    Shape  : {combined.shape[0]:,} rows × {combined.shape[1]} columns")
    print(f"    Range  : {str(combined.index[0])[:10]} → {str(combined.index[-1])[:10]}")
    print(f"    Columns: {', '.join(frames.keys())}")


# -------------------------------------------------------------
# Main
# -------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  📡  Macro Data Fetcher  (mixed provider)")
    print(f"  yfinance : {', '.join(YF_SYMBOLS.keys())}")
    print(f"  IBKR     : {', '.join(IBKR_SYMBOLS.keys())}")
    print("=" * 60 + "\n")

    frames = {}

    # 1. yfinance instruments
    for name, symbol in YF_SYMBOLS.items():
        df = fetch_yfinance_instrument(name, symbol)
        if df is not None:
            frames[name] = df

    # 2. IBKR instruments
    ibkr_frames = fetch_ibkr_instruments()
    frames.update(ibkr_frames)

    # 3. Save
    save_macro(frames)

    print("\n" + "=" * 60)
    print("  ✅  Done!")
    print(f"  Got: {', '.join(frames.keys())}")
    print("  Next: python data/validate_data.py")
    print("=" * 60)

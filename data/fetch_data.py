# fetch_data.py v2 — Binance via CCXT + Hyperliquid fallback
import os, sys, time, requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

try:
    import ccxt
except ImportError:
    print("ccxt not installed. Run: pip install ccxt")
    sys.exit(1)

# Derived from config.ASSETS — never hardcode coins here
HL_ONLY_COINS = {coin for coin, cfg in config.ASSETS.items() if cfg.get("source") == "hyperliquid"}

def binance_symbol(coin):
    return f"{coin}/USDT"

def fetch_from_binance(coin, interval, start_date: str = None, days: int = None):
    """
    Fetch OHLCV from Binance.
    Pass start_date (e.g. "2019-09-08") to fetch from a fixed date,
    or days (int) to fetch N days back from today.
    start_date takes priority if both are provided.
    """
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    symbol   = binance_symbol(coin)
    end_dt   = datetime.now(tz=timezone.utc)

    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    elif days:
        start_dt = end_dt - timedelta(days=days)
    else:
        start_dt = end_dt - timedelta(days=config.LOOKBACK_DAYS_DEFAULT)

    since_ms = int(start_dt.timestamp() * 1000)
    limit    = 1000

    print(f"  📥 {coin} {interval} from Binance | {start_dt.date()} → {end_dt.date()}")

    all_candles = []
    fetch_since = since_ms

    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol=symbol, timeframe=interval, since=fetch_since, limit=limit)
        except ccxt.BadSymbol:
            exchange.options["defaultType"] = "spot"
            try:
                candles = exchange.fetch_ohlcv(symbol=symbol, timeframe=interval, since=fetch_since, limit=limit)
            except Exception as e:
                print(f"  ❌ {coin} not on Binance: {e}")
                return pd.DataFrame()
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return pd.DataFrame()

        if not candles:
            break

        all_candles.extend(candles)
        last_ts = candles[-1][0]
        end_ms  = int(end_dt.timestamp() * 1000)

        if last_ts >= end_ms or len(candles) < limit:
            break

        fetch_since = last_ts + 1
        time.sleep(0.1)

    if not all_candles:
        print(f"  ❌ No data for {coin}")
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[df.index <= end_dt]
    print(f"  ✅ {len(df):,} candles received")
    return df

def to_ms(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

def from_ms(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

def fetch_from_hyperliquid(coin, interval, start_date: str = None, days: int = None):
    end_dt   = datetime.now(tz=timezone.utc)
    # Hyperliquid has a hard ~17 day cap regardless of what we request
    start_dt = end_dt - timedelta(days=17)
    print(f"  📥 {coin} {interval} from Hyperliquid | {start_dt.date()} → {end_dt.date()} (17d max)")

    all_chunks, chunk_start = [], start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(days=7), end_dt)
        payload = {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                   "startTime": to_ms(chunk_start), "endTime": to_ms(chunk_end)}}
        try:
            r = requests.post(config.HL_API_URL, json=payload, timeout=30)
            r.raise_for_status()
            raw = r.json()
            if raw:
                records = [{"timestamp": from_ms(c["t"]), "open": float(c["o"]), "high": float(c["h"]),
                            "low": float(c["l"]), "close": float(c["c"]), "volume": float(c["v"])} for c in raw]
                all_chunks.append(pd.DataFrame(records).set_index("timestamp"))
        except Exception as e:
            print(f"  ❌ HL error: {e}")
        chunk_start = chunk_end
        time.sleep(0.2)

    if not all_chunks:
        return pd.DataFrame()
    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    print(f"  ✅ {len(df):,} candles (HL limit applies)")
    return df

def fetch_candles_chunked(coin, interval, start_date: str = None, days: int = None):
    if coin.upper() in HL_ONLY_COINS:
        return fetch_from_hyperliquid(coin, interval, start_date=start_date, days=days)
    return fetch_from_binance(coin, interval, start_date=start_date, days=days)

def save_candles(df, coin, interval):
    if df.empty:
        return
    from sqlalchemy import create_engine
    os.makedirs(config.DATA_DIR, exist_ok=True)
    csv_path = os.path.join(config.DATA_DIR, f"{coin}_{interval}.csv")
    df.to_csv(csv_path)
    print(f"  💾 CSV → {csv_path}")
    engine = create_engine(f"sqlite:///{config.DB_PATH}")
    df_save = df.copy()
    df_save.index = df_save.index.astype(str)
    df_save.to_sql(f"{coin}_{interval}", con=engine, if_exists="replace", index=True, index_label="timestamp")
    print(f"  🗄️  DB  → {config.DB_PATH}")

def resample_candles(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """
    Resample 5m candles into any larger timeframe.
    No re-download needed — derive 15m, 1h, 4h, 1d from 5m data.

    Usage:
        df_5m = load_candles("BTC", "5m")
        df_1h = resample_candles(df_5m, "1h")
        df_4h = resample_candles(df_5m, "4h")
    """
    # Map friendly names to pandas offset strings
    tf_map = {
        "15m": "15min", "30m": "30min",
        "1h":  "1h",    "2h":  "2h",
        "4h":  "4h",    "6h":  "6h",
        "1d":  "1D",
    }
    freq = tf_map.get(target_tf, target_tf)
    df_resampled = df.resample(freq).agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    return df_resampled


def load_candles(coin, interval):
    """
    Load candles for a coin/timeframe.
    If the timeframe was not downloaded directly, resample from 5m.
    """
    csv_path = os.path.join(config.DATA_DIR, f"{coin}_{interval}.csv")

    # Direct file exists — load it
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, index_col="timestamp", parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    # Try resampling from 5m if available
    base_path = os.path.join(config.DATA_DIR, f"{coin}_5m.csv")
    if os.path.exists(base_path) and interval != "5m":
        print(f"  ♻️  Resampling {coin} 5m → {interval}")
        df_5m = pd.read_csv(base_path, index_col="timestamp", parse_dates=True)
        df_5m.index = pd.to_datetime(df_5m.index, utc=True)
        return resample_candles(df_5m, interval)

    raise FileNotFoundError(
        f"No data for {coin} {interval}. Run fetch_data.py first."
    )


def print_data_summary():
    candles_dir = Path(config.DATA_DIR)
    if not candles_dir.exists() or not list(candles_dir.glob("*.csv")):
        print("  ⚠️  No data yet.")
        return
    print(f"\n📊 Data Summary:")
    print(f"{'Coin':<8} {'TF':<6} {'Candles':>10} {'From':<14} {'To':<14} {'Days':>6}")
    print("─" * 58)
    for f in sorted(candles_dir.glob("*.csv")):
        parts = f.stem.split("_")
        coin, tf = parts[0], parts[1] if len(parts) > 1 else "?"
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            first = str(df.index[0])[:10]
            last  = str(df.index[-1])[:10]
            days  = (pd.to_datetime(df.index[-1]) - pd.to_datetime(df.index[0])).days
            print(f"{coin:<8} {tf:<6} {len(df):>10,} {first:<14} {last:<14} {days:>6}")
        except Exception:
            print(f"{coin:<8} {tf:<6} (error reading)")
    print()


# =============================================================
# INTERACTIVE CLI HELPERS
# =============================================================

def prompt_assets() -> list:
    """
    Ask the user which assets to download.
    Shows known assets from config.ASSETS plus option to type a custom one.
    """
    known = list(config.ASSETS.keys())

    print("\n  Known assets (from config):")
    for i, coin in enumerate(known, 1):
        cfg = config.ASSETS[coin]
        print(f"    [{i}] {coin:<6} — {cfg['source']}, from {cfg['start']}  ({cfg['note']})")
    print(f"    [a] All of the above")
    print(f"    [c] Enter a custom coin")

    choice = input("\n  Select assets (e.g. 1,3 or a or c): ").strip().lower()

    if choice == "a":
        return known

    if choice == "c":
        raw = input("  Enter coin symbol(s), comma-separated (e.g. ETH,WIF): ").strip().upper()
        return [c.strip() for c in raw.split(",") if c.strip()]

    # Numeric selection e.g. "1,3"
    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(known):
                selected.append(known[idx])
    return selected


def prompt_start_date(coin: str) -> str:
    """
    Ask the user for the start date for a given coin.
    Shows the default from config if available.
    """
    default = config.ASSETS.get(coin, {}).get("start", "")
    if default:
        prompt = f"  Start date for {coin} [{default}] (press Enter to use default): "
    else:
        prompt = f"  Start date for {coin} (YYYY-MM-DD): "

    raw = input(prompt).strip()
    if not raw and default:
        return default
    # Validate format
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    except ValueError:
        print(f"  ⚠️  Invalid date '{raw}', using default '{default or 'today-365d'}'")
        return default


def prompt_source(coin: str) -> str:
    """Ask which exchange to use for a coin not in config."""
    default_source = config.ASSETS.get(coin, {}).get("source", "binance")
    raw = input(f"  Source for {coin} [binance/hyperliquid] (default: {default_source}): ").strip().lower()
    if raw in ("binance", "hyperliquid"):
        return raw
    return default_source


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🚀  Data Fetcher — Interactive")
    print("=" * 60)

    # ── Step 1: which assets? ─────────────────────────────────
    coins = prompt_assets()
    if not coins:
        print("  ❌ No assets selected. Exiting.")
        sys.exit(0)

    # ── Step 2: start date per asset ─────────────────────────
    print()
    jobs = []   # list of (coin, start_date, source)
    for coin in coins:
        start_date = prompt_start_date(coin)
        source     = prompt_source(coin) if coin not in config.ASSETS else config.ASSETS[coin]["source"]
        jobs.append((coin, start_date, source))

    # ── Step 3: confirm ───────────────────────────────────────
    print("\n  📋 Download plan:")
    print(f"  {'Coin':<8} {'Source':<14} {'From':<14} {'TF'}")
    print("  " + "─" * 46)
    for coin, start_date, source in jobs:
        tfs = ", ".join(config.DOWNLOAD_TIMEFRAMES)
        print(f"  {coin:<8} {source:<14} {start_date:<14} {tfs}")

    confirm = input("\n  Proceed? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("  Cancelled.")
        sys.exit(0)

    # ── Step 4: fetch ─────────────────────────────────────────
    print()
    total = len(jobs) * len(config.DOWNLOAD_TIMEFRAMES)
    done  = 0

    for coin, start_date, source in jobs:
        for interval in config.DOWNLOAD_TIMEFRAMES:
            done += 1
            print(f"\n[{done}/{total}] {coin} {interval} — from {start_date} via {source}")

            # Temporarily override source for custom coins
            original_hl = set(HL_ONLY_COINS)
            if source == "hyperliquid":
                HL_ONLY_COINS.add(coin.upper())
            else:
                HL_ONLY_COINS.discard(coin.upper())

            df = fetch_candles_chunked(coin, interval, start_date=start_date)

            # Restore
            HL_ONLY_COINS.clear()
            HL_ONLY_COINS.update(original_hl)

            if not df.empty:
                save_candles(df, coin, interval)

    print("\n" + "=" * 60)
    print("  ✅ Done!")
    print_data_summary()
    print("  Next steps:")
    print("    python data/fetch_dvol.py")
    print("    python data/fetch_macro.py")
    print("    python data/validate_data.py")
    print("    python data/standardize_data.py")
    print("    python backtest/engine.py")
    print("=" * 60)

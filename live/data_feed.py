# =============================================================
# live/data_feed.py
# =============================================================
# Fetches live 5m candles from Hyperliquid for all active coins.
# Builds a rolling window of candles sufficient for strategy
# signal generation (EMA16 on 4h = needs ~200 4h candles =
# ~2400 5m candles to be safe).
#
# Usage:
#   from live.data_feed import DataFeed
#   feed = DataFeed()
#   df = feed.get_candles("SOL")   # returns 5m DataFrame
# =============================================================

import time
import requests
import pandas as pd
from datetime import datetime, timezone

# Hyperliquid name mapping — backtest name → live name
COIN_MAP = {
    "PEPE": "kPEPE",
    "SOL":  "SOL",
    "AAVE": "AAVE",
    "DOGE": "DOGE",
    "LINK": "LINK",
    "ETH":  "ETH",
    "XRP":  "XRP",
}

# How many 5m candles to fetch — enough for 200 4h candles + warmup
CANDLE_LOOKBACK = 2500   # ~8.7 days of 5m candles
API_URL         = "https://api.hyperliquid.xyz/info"


class DataFeed:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _fetch_candles(self, hl_coin: str, interval: str = "5m",
                       n_candles: int = CANDLE_LOOKBACK) -> pd.DataFrame:
        """
        Fetch recent candles from Hyperliquid REST API.
        Returns DataFrame with OHLCV indexed by UTC timestamp.
        """
        end_ms   = int(time.time() * 1000)
        # 5m = 300s, fetch enough history
        start_ms = end_ms - (n_candles * 300 * 1000)

        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin":      hl_coin,
                "interval":  interval,
                "startTime": start_ms,
                "endTime":   end_ms,
            }
        }

        resp = self.session.post(API_URL, json=payload, timeout=10)
        resp.raise_for_status()
        candles = resp.json()

        if not candles:
            raise ValueError(f"No candles returned for {hl_coin}")

        df = pd.DataFrame(candles)
        df = df.rename(columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        })
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df = df.sort_index()

        # Drop the last (incomplete) candle
        df = df.iloc[:-1]

        return df

    def get_candles(self, backtest_coin: str) -> pd.DataFrame:
        """
        Get 5m candles for a coin using backtest naming convention.
        Translates to Hyperliquid name internally.
        """
        hl_coin = COIN_MAP.get(backtest_coin)
        if not hl_coin:
            raise ValueError(f"Unknown coin: {backtest_coin}. Add to COIN_MAP.")
        return self._fetch_candles(hl_coin)

    def get_latest_price(self, backtest_coin: str) -> float:
        """Get current mid price for a coin."""
        hl_coin = COIN_MAP.get(backtest_coin)
        resp = self.session.post(API_URL,
            json={"type": "allMids"}, timeout=5)
        mids = resp.json()
        price = mids.get(hl_coin)
        if price is None:
            raise ValueError(f"No mid price found for {hl_coin}")
        return float(price)


if __name__ == "__main__":
    feed = DataFeed()
    for coin in COIN_MAP:
        try:
            df = feed.get_candles(coin)
            price = feed.get_latest_price(coin)
            print(f"{coin:<6} ({COIN_MAP[coin]:<8}) "
                  f"candles={len(df)}  "
                  f"latest={df.index[-1].strftime('%Y-%m-%d %H:%M')}  "
                  f"price={price:.6f}")
        except Exception as e:
            print(f"{coin:<6} ERROR: {e}")

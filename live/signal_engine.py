# =============================================================
# live/signal_engine.py
# =============================================================
# Runs EMA16 V8A strategy on live candle data.
# Identical logic to strategies/ema16/strategy.py but
# returns a structured signal dict instead of a DataFrame.
#
# Usage:
#   from live.signal_engine import SignalEngine
#   engine = SignalEngine()
#   signal = engine.get_signal("SOL", df_5m)
#   # signal = {"action": "long"|"short"|"exit_long"|"exit_short"|None,
#   #           "stop_loss": float, "entry_price": float}
# =============================================================

import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.ema16.params_v8a import get_default_params


class SignalEngine:

    def __init__(self):
        self.params = get_default_params()
        self.p      = self.params

    def get_signal(self, coin: str, df_5m: pd.DataFrame) -> dict:
        """
        Run V8A strategy on 5m candle DataFrame.

        Returns:
            dict with keys:
                action      : "long" | "short" | "exit_long" |
                              "exit_short" | None
                stop_loss   : float (ATR-based stop price)
                entry_price : float (current close)
                atr         : float (current ATR value)
                ema16       : float (current EMA16 value)
                rsi         : float (current RSI value)
                signal_raw  : int (1, -1, 0)
        """
        p = self.p

        # ── Resample 5m → 4h ─────────────────────────────────
        df = df_5m.resample("4h").agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
        }).dropna()

        if len(df) < p["ema_period"] * 2 + 20:
            return {"action": None, "reason": "insufficient data"}

        df = df.copy()

        # ── EMA16 ─────────────────────────────────────────────
        df["ema16"] = df["close"].ewm(
            span=p["ema_period"], adjust=False).mean()

        # ── RSI ───────────────────────────────────────────────
        delta     = df["close"].diff()
        gain      = delta.clip(lower=0)
        loss      = (-delta).clip(lower=0)
        avg_gain  = gain.ewm(span=p["rsi_period"], adjust=False).mean()
        avg_loss  = loss.ewm(span=p["rsi_period"], adjust=False).mean()
        rs        = avg_gain / avg_loss.replace(0, 1e-10)
        df["rsi"] = 100 - (100 / (1 + rs))

        # ── ATR stop ─────────────────────────────────────────
        hl  = df["high"] - df["low"]
        hc  = (df["high"] - df["close"].shift(1)).abs()
        lc  = (df["low"]  - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr = tr.ewm(span=p["atr_period"], adjust=False).mean()
        df["atr"]            = atr
        df["stop_loss_long"]  = df["close"] - atr * p["atr_stop_mult"]
        df["stop_loss_short"] = df["close"] + atr * p["atr_stop_mult"]

        # ── Signal generation ─────────────────────────────────
        prev_close = df["close"].shift(1)
        prev_ema   = df["ema16"].shift(1)
        cross_above = (df["close"] > df["ema16"]) & (prev_close <= prev_ema)
        cross_below = (df["close"] < df["ema16"]) & (prev_close >= prev_ema)

        df["signal"] = 0
        df.loc[cross_above, "signal"] =  1
        df.loc[cross_below, "signal"] = -1

        # ── Warmup removal ────────────────────────────────────
        warmup = p["ema_period"] * 2
        df = df.iloc[warmup:].copy()

        # ── Read last two candles ─────────────────────────────
        last  = df.iloc[-1]
        prev  = df.iloc[-2]

        signal_raw = int(last["signal"])
        rsi        = float(last["rsi"])
        close      = float(last["close"])
        ema16      = float(last["ema16"])
        sl_long    = float(last["stop_loss_long"])
        sl_short   = float(last["stop_loss_short"])
        atr_val    = float(last["atr"])

        # ── RSI filter ───────────────────────────────────────
        long_ok  = p["rsi_long_min"]  <= rsi <= p["rsi_long_max"]
        short_ok = p["rsi_short_min"] <= rsi <= p["rsi_short_max"]

        # ── Determine action ─────────────────────────────────
        action = None

        if signal_raw == 1 and long_ok:
            action = "long"
        elif signal_raw == -1 and short_ok:
            action = "short"
        elif signal_raw == -1:
            # EMA cross below = exit any long even if RSI not in short zone
            action = "exit_long"
        elif signal_raw == 1:
            # EMA cross above = exit any short
            action = "exit_short"

        return {
            "coin":        coin,
            "action":      action,
            "signal_raw":  signal_raw,
            "entry_price": close,
            "stop_loss_long":  sl_long,
            "stop_loss_short": sl_short,
            "atr":         round(atr_val, 8),
            "ema16":       round(ema16, 6),
            "rsi":         round(rsi, 2),
            "candle_time": str(df.index[-1]),
        }


if __name__ == "__main__":
    from live.data_feed import DataFeed
    feed   = DataFeed()
    engine = SignalEngine()
    coins  = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]

    print(f"\n{'Coin':<6} {'Action':<12} {'Price':<12} "
          f"{'SL Long':<12} {'RSI':<8} {'Candle'}")
    print("-" * 75)
    for coin in coins:
        try:
            df  = feed.get_candles(coin)
            sig = engine.get_signal(coin, df)
            print(f"{coin:<6} {str(sig['action']):<12} "
                  f"{sig['entry_price']:<12.6f} "
                  f"{sig['stop_loss_long']:<12.6f} "
                  f"{sig['rsi']:<8.2f} "
                  f"{sig['candle_time']}")
        except Exception as e:
            print(f"{coin:<6} ERROR: {e}")

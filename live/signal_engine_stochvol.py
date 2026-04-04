# =============================================================
# live/signal_engine_stochvol.py
# =============================================================
# Runs StochVol V1 strategy on live candle data.
# Returns structured signal dict for executor.
# =============================================================

import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.stochvol.params_v1 import get_default_params


class StochVolSignalEngine:

    def __init__(self):
        self.params = get_default_params()
        self.p      = self.params

    def get_signal(self, coin: str, df_5m: pd.DataFrame) -> dict:
        """
        Run StochVol V1 on 5m candle DataFrame.
        Returns signal dict with action, stop levels, vol_ratio.
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

        if len(df) < 50:
            return {"action": None, "reason": "insufficient data"}

        df = df.copy()

        # ── Stochastic(14, 3, 3) ─────────────────────────────
        k_period = p["stoch_k"]
        d_period = p["stoch_d"]
        smooth   = p["stoch_smooth"]

        lowest_low   = df["low"].rolling(k_period).min()
        highest_high = df["high"].rolling(k_period).max()
        raw_k        = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low + 1e-10)
        df["%K"]     = raw_k.rolling(smooth).mean()
        df["%D"]     = df["%K"].rolling(d_period).mean()

        # Stochastic cross
        prev_k      = df["%K"].shift(1)
        prev_d      = df["%D"].shift(1)
        cross_above = (df["%K"] > df["%D"]) & (prev_k <= prev_d)
        cross_below = (df["%K"] < df["%D"]) & (prev_k >= prev_d)

        df["signal"] = 0
        df.loc[cross_above, "signal"] =  1
        df.loc[cross_below, "signal"] = -1

        # ── Volume ────────────────────────────────────────────
        vol_period    = p["vol_period"]
        df["vol_avg"] = df["volume"].rolling(vol_period).mean()
        df["vol_ratio"] = df["volume"] / df["vol_avg"].replace(0, 1e-10)

        # Block low-volume entries
        df.loc[df["vol_ratio"] < p["vol_min_ratio"], "signal"] = 0

        # ── ATR stop ─────────────────────────────────────────
        hl  = df["high"] - df["low"]
        hc  = (df["high"] - df["close"].shift(1)).abs()
        lc  = (df["low"]  - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr = tr.ewm(span=p["atr_period"], adjust=False).mean()
        df["atr"]             = atr
        df["stop_loss_long"]  = df["close"] - atr * p["atr_stop_mult"]
        df["stop_loss_short"] = df["close"] + atr * p["atr_stop_mult"]

        # ── Warmup ────────────────────────────────────────────
        warmup = max(k_period + d_period + smooth, vol_period) + 5
        df     = df.iloc[warmup:].copy()

        if len(df) < 2:
            return {"action": None, "reason": "insufficient data after warmup"}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        signal_raw = int(last["signal"])
        close      = float(last["close"])
        vol_ratio  = float(last["vol_ratio"])
        sl_long    = float(last["stop_loss_long"])
        sl_short   = float(last["stop_loss_short"])
        k_val      = float(last["%K"])
        d_val      = float(last["%D"])

        # Determine action
        action = None
        if signal_raw == 1:
            action = "long"
        elif signal_raw == -1:
            action = "short"
        # Exit signals — cross in opposite direction
        prev_signal = int(prev["signal"])
        if signal_raw == -1 and prev_signal != -1:
            action = "short"
        if signal_raw == 1 and prev_signal != 1:
            action = "long"

        # Exit conditions from opposite cross
        if signal_raw == -1:
            exit_long = True
        else:
            exit_long = False

        if signal_raw == 1:
            exit_short = True
        else:
            exit_short = False

        return {
            "coin":           coin,
            "action":         action,
            "signal_raw":     signal_raw,
            "entry_price":    close,
            "stop_loss_long": sl_long,
            "stop_loss_short": sl_short,
            "vol_ratio":      round(vol_ratio, 4),
            "stoch_k":        round(k_val, 2),
            "stoch_d":        round(d_val, 2),
            "atr":            round(float(last["atr"]), 8),
            "exit_long":      exit_long,
            "exit_short":     exit_short,
            "candle_time":    str(df.index[-1]),
        }


if __name__ == "__main__":
    from live.data_feed import DataFeed, COIN_MAP
    feed   = DataFeed()
    engine = StochVolSignalEngine()
    coins  = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]

    print(f"\n{'Coin':<6} {'Action':<12} {'Vol Ratio':>10} {'%K':>6} {'%D':>6} {'Candle'}")
    print("-" * 65)
    for coin in coins:
        try:
            df  = feed.get_candles(coin)
            sig = engine.get_signal(coin, df)
            print(f"{coin:<6} {str(sig['action']):<12} "
                  f"{sig['vol_ratio']:>10.3f} "
                  f"{sig['stoch_k']:>6.1f} "
                  f"{sig['stoch_d']:>6.1f} "
                  f"{sig['candle_time'][:16]}")
        except Exception as e:
            print(f"{coin:<6} ERROR: {e}")

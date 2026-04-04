# =============================================================
# data/regime_filter.py — Unified Macro + IV Regime Filter
# =============================================================
#
# WHAT THIS DOES:
#   Combines BTC DVOL (implied volatility) and macro data
#   (VIX, DXY, yields) into a single "should I trade?" answer
#   for the engine.
#
#   The engine calls:
#       regime = RegimeFilter()
#       if regime.allow_trade(timestamp, strategy="Breakout"):
#           # take the trade
#
# HOW REGIMES WORK:
#
#   DVOL regime (from BTC options — real-time):
#     low    → market expects tiny moves → breakouts fake out
#     normal → standard conditions → trade normally
#     high   → strong moves expected → breakouts have follow-through
#     crisis → extreme volatility → reduce size
#
#   Macro regime (from VIX/DXY — 15min delayed, IBKR when ready):
#     risk_on  → VIX low, DXY falling → good for crypto longs
#     neutral  → mixed signals → trade cautiously
#     risk_off → VIX high, DXY rising → avoid longs, shorts only
#
#   Combined regime → final trade gate
#
# FAIL-SAFE BEHAVIOR:
#   If any data file is missing, the filter ALLOWS trades.
#   Your bot never gets blocked by a missing data file.
# =============================================================

import os
import sys
import pandas as pd
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ─────────────────────────────────────────────────────────────
# THRESHOLDS — tune these after reviewing your data
# ─────────────────────────────────────────────────────────────

# DVOL (BTC implied volatility)
DVOL_LOW    = 45    # below → calm, skip breakouts
DVOL_NORMAL = 70    # 45-70 → normal
DVOL_HIGH   = 90    # 70-90 → elevated, breakouts run
DVOL_CRISIS = 120   # above → extreme, reduce size

# VIX (equity fear gauge)
VIX_CALM    = 18    # below → equity markets calm, risk-on
VIX_NORMAL  = 25    # 18-25 → normal
VIX_FEAR    = 35    # above → risk-off, be cautious

# DXY change threshold (% over last 5 days)
DXY_RISING  = 0.5   # DXY up >0.5% in 5 days = dollar strengthening = bad for crypto

# Yield curve inversion threshold
YIELD_INVERSION = 0.0   # 10Y - 2Y < 0 = inverted = recession fear


class RegimeFilter:
    """
    Unified regime filter for the backtest engine and live trader.

    Loads DVOL and macro data once at startup, then answers
    per-candle questions instantly via index lookup.
    """

    def __init__(self):
        self.dvol_df  = self._load_dvol()
        self.macro_df = self._load_macro()

        # Pre-compute regime labels for speed
        self._dvol_regime  = self._compute_dvol_regime()
        self._macro_regime = self._compute_macro_regime()

        self._report_status()

    # ─────────────────────────────────────────────────────────
    # LOADERS
    # ─────────────────────────────────────────────────────────

    def _load_dvol(self) -> pd.DataFrame | None:
        path = os.path.join(config.DATA_DIR, "BTC_DVOL_1h.csv")
        if not os.path.exists(path):
            print("  ⚠️  RegimeFilter: DVOL file not found — run data/fetch_dvol.py")
            return None
        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    def _load_macro(self) -> pd.DataFrame | None:
        path = os.path.join(config.DATA_DIR, "macro_1h.csv")
        if not os.path.exists(path):
            print("  ⚠️  RegimeFilter: Macro file not found — run data/fetch_macro.py")
            return None
        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    # ─────────────────────────────────────────────────────────
    # REGIME COMPUTATION (done once at load, not per candle)
    # ─────────────────────────────────────────────────────────

    def _compute_dvol_regime(self) -> pd.Series | None:
        if self.dvol_df is None or "close" not in self.dvol_df.columns:
            return None

        dvol = self.dvol_df["close"]
        conditions = [
            dvol >= DVOL_CRISIS,
            dvol >= DVOL_HIGH,
            dvol >= DVOL_NORMAL,
        ]
        choices = ["crisis", "high", "normal"]
        return pd.Series(
            np.select(conditions, choices, default="low"),
            index=dvol.index
        )

    def _compute_macro_regime(self) -> pd.Series | None:
        if self.macro_df is None:
            return None

        df = self.macro_df.copy()
        regimes = pd.Series("neutral", index=df.index)

        try:
            # Risk-off: VIX spiking
            if "VIX" in df.columns:
                vix_high = df["VIX"] > VIX_FEAR
                regimes[vix_high] = "risk_off"

            # Risk-off: DXY rising (bad for crypto)
            if "DXY" in df.columns:
                dxy_5d_change = df["DXY"].pct_change(5 * 24) * 100  # 5 days * 24h
                dxy_rising = dxy_5d_change > DXY_RISING
                regimes[dxy_rising & (regimes != "risk_off")] = "risk_off"

            # Risk-off: yield curve inverted
            if "US10Y" in df.columns and "US2Y" in df.columns:
                curve = df["US10Y"] - df["US2Y"]
                inverted = curve < YIELD_INVERSION
                # Only flag if also VIX elevated — inversion alone isn't enough
                if "VIX" in df.columns:
                    vix_elevated = df["VIX"] > VIX_NORMAL
                    regimes[inverted & vix_elevated & (regimes != "risk_off")] = "risk_off"

            # Risk-on: VIX calm, DXY stable or falling
            if "VIX" in df.columns:
                vix_calm = df["VIX"] < VIX_CALM
                regimes[vix_calm & (regimes == "neutral")] = "risk_on"

        except Exception as e:
            print(f"  ⚠️  RegimeFilter: macro regime error: {e}")

        return regimes

    # ─────────────────────────────────────────────────────────
    # LOOKUP HELPERS
    # ─────────────────────────────────────────────────────────

    def _get_at(self, series: pd.Series, timestamp: pd.Timestamp,
                default: str) -> str:
        """Get the most recent value at or before timestamp."""
        if series is None:
            return default
        available = series[series.index <= timestamp]
        if available.empty:
            return default
        return available.iloc[-1]

    def get_dvol_regime(self, timestamp: pd.Timestamp) -> str:
        """Returns: 'low', 'normal', 'high', 'crisis', or 'unknown'"""
        return self._get_at(self._dvol_regime, timestamp, "unknown")

    def get_macro_regime(self, timestamp: pd.Timestamp) -> str:
        """Returns: 'risk_on', 'neutral', 'risk_off', or 'unknown'"""
        return self._get_at(self._macro_regime, timestamp, "unknown")

    def get_dvol_value(self, timestamp: pd.Timestamp) -> float | None:
        """Get raw DVOL number at timestamp."""
        if self.dvol_df is None:
            return None
        available = self.dvol_df[self.dvol_df.index <= timestamp]
        if available.empty:
            return None
        return available.iloc[-1]["close"]

    # ─────────────────────────────────────────────────────────
    # MAIN GATE — called by engine per candle
    # ─────────────────────────────────────────────────────────

    def allow_trade(self, timestamp: pd.Timestamp,
                    strategy: str = "any",
                    direction: str = "both") -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).

        Rules:
          Breakout / SuperTrend:
            - Blocked if DVOL = low (fake breakouts)
            - Blocked if macro = risk_off AND direction = long
            - Allowed in all other conditions

          Momentum:
            - Blocked if macro = risk_off AND direction = long
            - Allowed in all other conditions

          Any other strategy:
            - Always allowed (fail-open)

        The reason string is stored in trade metadata for analysis.
        """
        dvol_regime  = self.get_dvol_regime(timestamp)
        macro_regime = self.get_macro_regime(timestamp)

        # ── Breakout and SuperTrend need real volatility ──────
        if strategy in ("Breakout", "SuperTrend"):
            if dvol_regime == "low":
                return False, f"DVOL_LOW({self.get_dvol_value(timestamp):.0f})"

        # ── All strategies: no longs in risk-off macro ────────
        if macro_regime == "risk_off" and direction == "long":
            return False, f"MACRO_RISK_OFF"

        # ── DVOL crisis: allow but flag for size reduction ────
        if dvol_regime == "crisis":
            return True, f"DVOL_CRISIS_REDUCE_SIZE"

        return True, f"OK({dvol_regime}/{macro_regime})"

    # ─────────────────────────────────────────────────────────
    # CURRENT STATUS — called at engine startup
    # ─────────────────────────────────────────────────────────

    def _report_status(self):
        now = pd.Timestamp.now(tz="UTC")

        dvol_val    = self.get_dvol_value(now)
        dvol_regime = self.get_dvol_regime(now)
        macro_regime = self.get_macro_regime(now)

        dvol_str = f"{dvol_val:.1f} ({dvol_regime})" if dvol_val else "unavailable"

        print(f"  📊 RegimeFilter loaded:")
        print(f"     DVOL         : {dvol_str}")
        print(f"     Macro regime : {macro_regime}")

        if dvol_val:
            daily_move = dvol_val / 20
            print(f"     Expected daily BTC move: ±{daily_move:.1f}%")

    def summary(self) -> dict:
        """Return current regime state as a dict for metadata."""
        now = pd.Timestamp.now(tz="UTC")
        return {
            "dvol_value":   self.get_dvol_value(now),
            "dvol_regime":  self.get_dvol_regime(now),
            "macro_regime": self.get_macro_regime(now),
            "provider":     getattr(config, "MACRO_PROVIDER", "yfinance"),
        }

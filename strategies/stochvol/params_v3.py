# =============================================================
# strategies/stochvol/params_v3.py
# =============================================================
# StochVol V3: Wider stoch periods + extended entry window
#
# Changes vs V1:
#   1. Stochastic(21, 5, 5) — smoother signals, fewer but
#      higher quality crosses, less noise in choppy markets
#   2. entry_window: 3 — fire entry on cross candle OR up to
#      2 candles after, IF K still on correct side of D
#   3. vol_min_ratio: 0.5 — looser volume gate (was 0.7)
#
# Hypothesis:
#   Smoother stoch reduces false crosses. Wider entry window
#   catches moves that started before vol confirmed. Lower vol
#   gate lets more trades through while sizing still rewards
#   high volume candles.
#
# Status: backtesting
# =============================================================

def get_default_params() -> dict:
    return {
        # ── Stochastic ────────────────────────────────────────
        "stoch_k":      21,    # %K period (V1: 14)
        "stoch_d":       5,    # %D smoothing (V1: 3)
        "stoch_smooth":  5,    # %K smoothing (V1: 3)

        # ── Entry window ──────────────────────────────────────
        "entry_window":  3,    # candles after cross to allow entry (V1: 1)

        # ── Volume ────────────────────────────────────────────
        "vol_period":   20,
        "vol_min_ratio": 0.5,  # min volume to allow entry (V1: 0.7)
        "vol_size_min":  1.0,
        "vol_size_max":  2.0,

        # ── ATR stop ──────────────────────────────────────────
        "atr_period":    14,
        "atr_stop_mult": 0.7,

        # ── Trail stop ────────────────────────────────────────
        "trail_trigger":       0.005,
        "trail_offset":        0.003,
        "trail_tight_trigger": 0.03,
        "trail_tight_offset":  0.002,

        # ── Volume dry-up partial exit ────────────────────────
        "vol_dry_threshold": 0.50,
        "vol_dry_close_pct": 0.60,

        # ── Risk ──────────────────────────────────────────────
        "risk_pct": 0.005,
    }

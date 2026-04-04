# =============================================================
# strategies/stochvol/params_v4.py
# =============================================================
# StochVol V4: Faster stoch + looser volume gate
#
# Changes vs V3:
#   1. stoch_k: 14 (was 21) — faster signal, catches moves earlier
#   2. vol_min_ratio: 0.3 (was 0.5) — looser volume gate,
#      more trades through while sizing still rewards high vol
#
# Unchanged vs V3:
#   entry_window=3, stoch_d=5, stoch_smooth=5, atr_stop_mult=0.7
#   all trail/exit params identical
#
# Source: Stage 2 basket optimizer — won 3/4 windows vs V3 0/4
# Validated: walk-forward required before live promotion
# =============================================================

def get_default_params() -> dict:
    return {
        # Stochastic
        "stoch_k":      14,    # V3: 21
        "stoch_d":       5,
        "stoch_smooth":  5,

        # Entry window
        "entry_window":  3,

        # Volume
        "vol_period":   20,
        "vol_min_ratio": 0.3,  # V3: 0.5
        "vol_size_min":  1.0,
        "vol_size_max":  2.0,

        # ATR stop
        "atr_period":    14,
        "atr_stop_mult": 0.7,

        # Trail stop
        "trail_trigger":       0.005,
        "trail_offset":        0.003,
        "trail_tight_trigger": 0.03,
        "trail_tight_offset":  0.002,

        # Volume dry-up partial exit
        "vol_dry_threshold": 0.50,
        "vol_dry_close_pct": 0.60,

        # Risk
        "risk_pct": 0.005,
    }

# =============================================================
# strategies/stochvol/params_v5_candidate.py
# =============================================================
# V5 candidate: entry_window=4, vol_min_ratio=0.2
#
# Changes vs V4:
#   1. entry_window: 4 (was 3) — wider entry window, strongest
#      lever from Stage A optimization (Sharpe 8.64 vs 7.97)
#   2. vol_min_ratio: 0.2 (was 0.3) — looser volume gate,
#      marginal improvement (Sharpe 7.93 vs 7.91)
#
# Unchanged vs V4:
#   stoch_k=14, stoch_d=5, stoch_smooth=5, atr_stop_mult=0.7
#   all trail/exit params identical
#
# Source: Stage A entry optimizer — won 3/4 OOS windows vs V4 0/4
# Status: CANDIDATE — shadow testing on Wallet 1 only
# =============================================================

def get_default_params() -> dict:
    return {
        # Stochastic
        "stoch_k":      14,
        "stoch_d":       5,
        "stoch_smooth":  5,

        # Entry window
        "entry_window":  4,    # V4: 3

        # Volume
        "vol_period":   20,
        "vol_min_ratio": 0.2,  # V4: 0.3
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

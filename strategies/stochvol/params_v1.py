# =============================================================
# strategies/stochvol/params_v1.py — FROZEN 2026-03-25
# =============================================================
# StochVol V1: Stochastic(14,3,3) cross + volume confirmation
#
# Core idea:
#   Entry on stochastic %K/%D cross with volume confirmation.
#   Position size scales with volume strength.
#   Exit via trail stop + volume dry-up partial close.
#
# Status: testing
# =============================================================

def get_default_params() -> dict:
    return {
        # ── Stochastic ────────────────────────────────────────
        "stoch_k":      14,    # %K period
        "stoch_d":       3,    # %D smoothing
        "stoch_smooth":  3,    # %K smoothing

        # ── Volume ────────────────────────────────────────────
        "vol_period":   20,    # rolling average period
        "vol_min_ratio": 0.7,  # min volume to allow entry (70% of avg)
        "vol_size_min":  1.0,  # min position size multiplier
        "vol_size_max":  2.0,  # max position size multiplier (cap at 2×)

        # ── ATR stop ──────────────────────────────────────────
        "atr_period":    14,
        "atr_stop_mult": 0.7,

        # ── Trail stop ────────────────────────────────────────
        "trail_trigger":       0.005,  # activate at +0.5%
        "trail_offset":        0.003,  # trail 0.3% behind best
        "trail_tight_trigger": 0.03,   # tighten at +3%
        "trail_tight_offset":  0.002,  # trail 0.2% behind best

        # ── Volume dry-up partial exit ────────────────────────
        "vol_dry_threshold": 0.50,  # exit partial if vol < 50% avg
        "vol_dry_close_pct": 0.60,  # close 60% of position

        # ── Risk ──────────────────────────────────────────────
        "risk_pct": 0.005,
    }

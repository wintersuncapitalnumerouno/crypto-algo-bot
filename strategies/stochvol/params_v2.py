# =============================================================
# strategies/stochvol/params_v2.py — FROZEN 2026-03-26
# =============================================================
# StochVol V2: Same as V1 but with adaptive ATR stop.
#
# Key change vs V1:
#   - Normal volume (< 1.5x avg): ATR × 0.7 stop (tight)
#   - High volume  (≥ 1.5x avg): ATR × 1.0 stop (wider)
#
# Hypothesis: wider stop on high-volume entries gives the trade
# more room to breathe, reducing stop-outs on strong momentum
# moves. Smaller position size (due to wider stop) also reduces
# dollar drawdown on losing trades.
#
# Status: testing
# =============================================================

def get_default_params() -> dict:
    return {
        # ── Stochastic ────────────────────────────────────────
        "stoch_k":      14,
        "stoch_d":       3,
        "stoch_smooth":  3,

        # ── Volume ────────────────────────────────────────────
        "vol_period":    20,
        "vol_min_ratio": 0.7,
        "vol_size_min":  1.0,
        "vol_size_max":  2.0,

        # ── ATR stop — adaptive ───────────────────────────────
        "atr_period":         14,
        "atr_stop_mult":      0.7,   # normal volume entries
        "atr_stop_mult_high": 1.0,   # high volume entries
        "vol_high_threshold": 1.5,   # volume ratio to switch to wider stop

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

# =============================================================
# strategies/ema16/params_v8c.py — FROZEN 2026-03-23
# =============================================================
# EMA16 V8C: ATR × 0.5 — tight boundary check
# =============================================================
def get_default_params() -> dict:
    return {
        "ema_period":    16,
        "rsi_period":    14,
        "rsi_long_min":  52,
        "rsi_long_max":  65,
        "rsi_short_min": 35,
        "rsi_short_max": 48,
        "atr_period":      14,
        "atr_stop_mult":   0.5,
        "use_atr_sizing":  True,
        "trail_trigger":       0.005,
        "trail_offset":        0.003,
        "trail_tight_trigger": 0.03,
        "trail_tight_offset":  0.002,
        "risk_pct": 0.005,
    }

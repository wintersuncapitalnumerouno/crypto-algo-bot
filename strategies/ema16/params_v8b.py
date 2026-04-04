# =============================================================
# strategies/ema16/params_v8b.py — FROZEN 2026-03-23
# =============================================================
# EMA16 V8B: ATR stop placement + adaptive sizing
#
# Changes from V8A:
#   - use_atr_sizing: True — position sized from actual stop distance
#   - Everything else identical to V8A
#
# Purpose:
#   Comparison V8A vs V8B = "does adaptive sizing add value?"
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
        "atr_stop_mult":   0.7,
        "use_atr_sizing":  True,  # sizing from actual ATR stop distance
        "trail_trigger":       0.005,
        "trail_offset":        0.003,
        "trail_tight_trigger": 0.03,
        "trail_tight_offset":  0.002,
        "risk_pct": 0.005,
    }

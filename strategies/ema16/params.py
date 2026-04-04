def get_default_params() -> dict:
    return {
        "ema_period":    16,
        "rsi_period":    14,
        "rsi_long_min":  52,
        "rsi_long_max":  65,
        "rsi_short_min": 35,
        "rsi_short_max": 48,
        "trail_trigger": 0.005,
        "trail_offset":  0.003,
        "stop_pct":      0.02,
        "risk_pct":      0.005,
    }

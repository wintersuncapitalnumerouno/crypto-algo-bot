# strategies/momentum/params.py
# Momentum v2 — EMA crossover + ADX strength + 4h trend filter
# This is the ONLY file you edit to tune this strategy.

def get_default_params() -> dict:
    return {
        "fast_ema":        9,
        "slow_ema":        21,
        "adx_period":      14,
        "adx_min":         25,
        "htf_ema":         50,
        "atr_period":      14,
        "atr_multiplier":  2.0,
        "rr_ratio":        2.0,
        "trail_atr_mult":  1.5,
        "trail_trigger":   1.0,
    }

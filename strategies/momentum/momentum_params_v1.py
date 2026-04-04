# =============================================================
# strategies/momentum/params_v1.py — FROZEN 2026-03-16
# =============================================================
# Momentum v1: EMA 9/21 crossover, 15m, ADX + 4h HTF filter
# Status: architecture complete, awaiting full signal test
# =============================================================

def get_default_params() -> dict:
    return {
        "fast_ema":       9,
        "slow_ema":       21,
        "atr_period":     14,
        "atr_multiplier": 2.0,
        "rr_ratio":       2.0,
    }

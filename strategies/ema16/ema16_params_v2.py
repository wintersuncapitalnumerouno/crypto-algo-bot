# strategies/ema16/params.py — v2

def get_default_params() -> dict:
    return {
        "ema_period":    16,
        "rsi_period":    14,

        # RSI trend filter — neutral gap around 50 avoids chop
        "rsi_long_min":  52,    # long only if RSI >= 52
        "rsi_long_max":  65,    # long only if RSI <= 65 (not overbought)
        "rsi_short_min": 35,    # short only if RSI >= 35 (not oversold)
        "rsi_short_max": 48,    # short only if RSI <= 48

        # Trailing stop — lower trigger to activate sooner
        "trail_trigger": 0.005,  # activate after 0.5% profit
        "trail_offset":  0.003,  # trail 0.3% behind best price

        # Risk model reference (engine reads from config, but documented here)
        "stop_pct":      0.02,
        "risk_pct":      0.005,
    }

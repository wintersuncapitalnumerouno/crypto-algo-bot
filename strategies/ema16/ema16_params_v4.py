# =============================================================
# strategies/ema16/params_v4.py — FROZEN 2026-03-16
# =============================================================
# EMA16 v4: 4h candles | RSI zone filter | fixed 2% stop | scaled exits
# Results: Full history SOL +2108%, LINK +1239%, BTC +106%
#          2022 bear: SOL +145%, LINK +105%, BTC +29%
#          2023-2024: SOL +211%, LINK +168%, BTC +22%
# =============================================================

def get_default_params() -> dict:
    return {
        # ── Signal ───────────────────────────────────────────
        "ema_period":    16,
        "rsi_period":    14,
        "rsi_long_min":  52,
        "rsi_long_max":  65,
        "rsi_short_min": 35,
        "rsi_short_max": 48,

        # ── Fixed stop (v4 uses config.STOP_PCT = 2%) ─────────
        # use_atr_stop is NOT set → engine uses fixed 2%
        "stop_pct":      0.02,

        # ── Trailing stop ─────────────────────────────────────
        "trail_trigger": 0.005,
        "trail_offset":  0.003,

        # ── Risk ──────────────────────────────────────────────
        "risk_pct":      0.005,

        # tp_levels set in strategy.py via df.attrs:
        # [(0.02, 0.40), (0.025, 0.30), (0.03, 0.30)]
    }

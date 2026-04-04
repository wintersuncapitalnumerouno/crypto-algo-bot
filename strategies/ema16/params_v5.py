# =============================================================
# strategies/ema16/params_v5.py — FROZEN 2026-03-18
# =============================================================
# EMA16 v5: ATR-based stop only
# Single change from v4: fixed 2% stop → ATR × 2.5
# Everything else identical to v4.
# =============================================================

def get_default_params() -> dict:
    return {
        # ── Signal (unchanged from v4) ────────────────────────
        "ema_period":    16,
        "rsi_period":    14,
        "rsi_long_min":  52,
        "rsi_long_max":  65,
        "rsi_short_min": 35,
        "rsi_short_max": 48,

        # ── ATR stop (new in v5) ──────────────────────────────
        "atr_period":    14,     # ATR period on 4h candles
        "atr_stop_mult": 2.5,    # stop = entry ± ATR × this

        # ── Trailing stop (unchanged from v4) ─────────────────
        "trail_trigger": 0.005,
        "trail_offset":  0.003,

        # ── Risk reference ────────────────────────────────────
        "risk_pct":      0.005,

        # tp_levels set in strategy.py via df.attrs (unchanged):
        # [(0.02, 0.40), (0.025, 0.30), (0.03, 0.30)]
    }

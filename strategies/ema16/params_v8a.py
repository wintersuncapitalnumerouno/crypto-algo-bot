# =============================================================
# strategies/ema16/params_v8a.py — FROZEN 2026-03-23
# =============================================================
# EMA16 V8A: ATR stop placement only
#
# Changes from V7:
#   - stop_loss_long/short columns written by strategy (ATR-based)
#   - stop PLACEMENT uses ATR × 0.7
#   - position SIZING still uses fixed 2% (use_atr_sizing: False)
#   - trail logic identical to V7
#
# Purpose:
#   Isolates the effect of ATR stop placement only.
#   Comparison V7 vs V8A = "does ATR improve exits?"
# =============================================================
def get_default_params() -> dict:
    return {
        # ── Signal (unchanged from V7) ────────────────────────
        "ema_period":    16,
        "rsi_period":    14,
        "rsi_long_min":  52,
        "rsi_long_max":  65,
        "rsi_short_min": 35,
        "rsi_short_max": 48,
        # ── ATR stop ──────────────────────────────────────────
        "atr_period":      14,
        "atr_stop_mult":   0.7,   # stop placed at ATR × 0.7
        "use_atr_sizing":  False, # sizing uses fixed STOP_PCT
        # ── Trailing stop (unchanged from V7) ─────────────────
        "trail_trigger":       0.005,
        "trail_offset":        0.003,
        "trail_tight_trigger": 0.03,
        "trail_tight_offset":  0.002,
        # ── Risk ──────────────────────────────────────────────
        "risk_pct": 0.005,
    }

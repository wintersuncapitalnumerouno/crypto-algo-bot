# =============================================================
# strategies/ema16/params_v7.py — FROZEN 2026-03-22
# =============================================================
# EMA16 v7: dynamic trail tightening
#
# Changes from v5:
#   - trail_tight_trigger: once trade is up 3%, tighten trail
#   - trail_tight_offset:  tighten to 0.2% behind best price
#     (vs normal 0.3% — locks in more of big winners)
#   - Signal and ATR stop logic identical to v5
#   - No scaled exits (v5 trail stop outperformed v6 TP ladder)
#
# Design:
#   Normal trail: activates at +0.5%, trails 0.3% behind best
#   Tight trail:  kicks in at +3.0%, trails 0.2% behind best
#   Engine reads trail_tight_trigger/offset from df.attrs —
#   no hardcoding in engine required.
# =============================================================

def get_default_params() -> dict:
    return {
        # ── Signal (unchanged from v5) ────────────────────────
        "ema_period":    16,
        "rsi_period":    14,
        "rsi_long_min":  52,
        "rsi_long_max":  65,
        "rsi_short_min": 35,
        "rsi_short_max": 48,

        # ── ATR stop (unchanged from v5) ──────────────────────
        "atr_period":    14,
        "atr_stop_mult": 2.5,

        # ── Trailing stop — normal phase ──────────────────────
        "trail_trigger": 0.005,   # activate after +0.5% profit
        "trail_offset":  0.003,   # trail 0.3% behind best price

        # ── Trailing stop — tight phase (new in v7) ───────────
        "trail_tight_trigger": 0.03,    # tighten once up +3%
        "trail_tight_offset":  0.002,   # trail 0.2% behind best price

        # ── Risk reference ────────────────────────────────────
        "risk_pct":      0.005,
    }

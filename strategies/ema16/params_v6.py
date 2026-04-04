# =============================================================
# strategies/ema16/params_v6.py — FROZEN 2026-03-22
# =============================================================
# EMA16 v6: scaled exits restored + retuned TP ladder
#
# Changes from v5:
#   - tp_levels re-enabled (were disabled in v5 strategy.py)
#   - TP ladder retuned from trade distribution analysis:
#       v5 ladder: 2.0% / 2.5% / 3.0%  ← never hit, too far
#       v6 ladder: 1.5% / 2.5% / 4.0%  ← fits actual exit dist
#   - Signal and stop logic identical to v5
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

        # ── Trailing stop (unchanged from v5) ─────────────────
        "trail_trigger": 0.005,
        "trail_offset":  0.003,

        # ── Risk reference ────────────────────────────────────
        "risk_pct":      0.005,

        # ── Scaled exits (restored + retuned) ─────────────────
        # Tuned from PEPE trade distribution (221 trades, chop period):
        #   42% exit 0-2%  → TP1 at 1.5% locks in early profits
        #   34% pass 2%    → TP2 at 2.5% captures mid winners
        #   19% pass 3%    → TP3 at 4.0% lets tail runners breathe
        # Weights sum to 1.0
        "tp_levels": [
            (0.015, 0.40),   # TP1: +1.5% → close 40% of position
            (0.025, 0.30),   # TP2: +2.5% → close 30% of position
            (0.040, 0.30),   # TP3: +4.0% → close 30% of position
        ],
    }

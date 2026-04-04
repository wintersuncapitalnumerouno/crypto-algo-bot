# crypto-algo-bot — Baseline Freeze
## EMA16 V7 — First Coherent State
**Date:** 2026-03-23  
**Status:** FROZEN BASELINE

---

## Active Files

| File | Path | Role |
|------|------|------|
| `engine.py` | `backtest/engine.py` | Execution engine — trail tight logic live |
| `strategy.py` | `strategies/ema16/strategy.py` | Signal logic — passes trail attrs from params |
| `params_v5.py` | `strategies/ema16/params_v5.py` | Frozen — archived reference baseline |
| `params_v7.py` | `strategies/ema16/params_v7.py` | Frozen — active baseline |
| `registry.py` | `strategies/registry.py` | V4, V5, V6, V7 registered |

---

## Engine State — VERIFIED

- Position sizing: fixed `STOP_PCT = 2%` (config)
- Trail logic: two-phase dynamic trail (normal + tight)
  - `trail_trigger` and `trail_offset` read from `df.attrs`
  - `trail_tight_trigger` and `trail_tight_offset` read from `df.attrs`
  - Tight trail activates when profit ≥ `trail_tight_trigger`
  - Falls back to normal offset if tight params are absent
- MTM equity: bar-by-bar, used for DD, Sharpe, Sortino
- Sharpe/Sortino: daily resampled MTM, `sqrt(365)`
- TP Hits counter: counts all `exit_reasons` starting with `tp`
- Parent trade stats: `trades_parent.csv` saved per coin folder

---

## Strategy State — VERIFIED

- Signal: EMA16 cross on 4h candles
- Filter: RSI 52–65 long, 35–48 short
- Stop: not written as column — engine uses fixed 2% fallback
- Trail attrs: `trail_trigger`, `trail_offset`, `trail_tight_trigger`, `trail_tight_offset` passed via `df.attrs`
- Scaled exits: driven by `tp_levels` in params if present

---

## Version Hierarchy

| Version | Status | Key Change |
|---------|--------|------------|
| V4 | Archived | EMA16 4h, fixed 2% stop, scaled exits 40/30/30 |
| V5 | Archived reference | ATR 2.5× stop in params, trail stop only |
| V6 | Rejected | Scaled exits 1.5/2.5/4.0% — cut winners short |
| V7 | **Active baseline** | Dynamic trail: 0.3% normal, 0.2% above +3% |

---

## Verified Baseline Results — EMA16 V7
**Period:** 2024-03-23 → 2026-03-23 (2-year)  
**Tag:** `v5_vs_v7_trail_fix`

| Coin | Return | Sharpe | Sortino | Max DD | Win Rate |
|------|--------|--------|---------|--------|----------|
| PEPE | +733.0% | 7.99 | 17.08 | -2.61% | 81.2% |
| SOL | +197.2% | 6.67 | 8.34 | -3.44% | 77.2% |
| AAVE | +278.0% | 6.42 | 9.20 | -3.68% | 76.3% |
| LINK | +226.8% | 6.15 | 9.53 | -4.39% | 77.1% |
| DOGE | +192.3% | 5.95 | 10.64 | -3.13% | 75.1% |
| ETH | +100.2% | 4.59 | 5.24 | -3.41% | 68.2% |
| XRP | +112.0% | 4.53 | 6.27 | -3.93% | 67.9% |
| BTC | +17.6% | 1.71 | 1.74 | -4.18% | 63.2% |
| BNB | +20.0% | 1.59 | 1.88 | -5.93% | 60.6% |

---

## Coin Tier Ranking — VERIFIED across 3 periods

| Tier | Coins | Evidence |
|------|-------|----------|
| T1 — Elite | PEPE, SOL, AAVE, DOGE | Strong in bear, chop, and bull |
| T2 — Solid | LINK, ETH, XRP | Good in trend, degrades in chop |
| Cut candidate | BTC, BNB | Consistently weakest Sharpe, highest DD |
| Low sample | HYPE | 9 trades — data starts Nov 2024 |

---

## Known Open Issues

| Issue | Status | Notes |
|-------|--------|-------|
| Position sizing uses fixed 2% | Known limitation | Intentional for baseline — ATR stop is a future V8+ test |
| TP Hits = 0 in summary | Fixed in engine | Counter now reads `tp*` exit reasons correctly |
| ATR stop not applied | Deferred | ATR × 2.5 produces ~7-10% stop on 4h candles, shrinks positions by ~75% — to be handled as new strategy version |

---

## What Was Tested and Rejected

| Test | Result | Reason |
|------|--------|--------|
| Regime filter (DVOL + VIX + funding) | Rejected | Blocked 35–47% candles, hurt 5/9 coins |
| Scaled exits V6 (1.5/2.5/4.0%) | Rejected | TP ladder cut winners, trail stop outperformed |
| Breakeven stop after TP1 | Removed | Killed remaining position on normal pullbacks |
| ATR stop columns in strategy | Reverted | Position sizes dropped ~75%, returns collapsed |

---

## Architecture Rules — FROZEN

**Strategy owns:**
- Indicator logic (EMA, RSI)
- Signal generation
- Trail params via `df.attrs`
- TP levels via `df.attrs`
- Stop columns (future — not yet implemented)

**Engine owns:**
- Generic execution
- Position sizing from stop distance
- MTM equity tracking
- Reporting

**To add a new experiment:**
1. Create `params_vN.py`
2. Add entry to `registry.py`
3. Run `--strategy EMA16_VN --tag description`
4. Do not touch `engine.py` or `strategy.py`

---

## Next Planned Test

**EMA16 V8 — Cooldown after stop loss**
- One variable change: add `cooldown_candles` param
- After `stop_loss` exit only (not trail, not signal, not time)
- Block re-entry for N × 4h candles
- Compare V7 vs V8 on same date range and coin set

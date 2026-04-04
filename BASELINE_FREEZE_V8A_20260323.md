# crypto-algo-bot — Baseline Freeze
## EMA16 V8A — Active Baseline
**Date:** 2026-03-23  
**Previous baseline:** EMA16 V7  
**Status:** FROZEN BASELINE

---

## Active Files

| File | Path | Role |
|------|------|------|
| `engine.py` | `backtest/engine.py` | Execution engine — trail tight + ATR stop column reading |
| `strategy.py` | `strategies/ema16/strategy.py` | Signal logic — ATR stop columns + trail attrs from params |
| `params_v7.py` | `strategies/ema16/params_v7.py` | Frozen — archived reference |
| `params_v8a.py` | `strategies/ema16/params_v8a.py` | Frozen — active baseline |
| `registry.py` | `strategies/registry.py` | V4, V5, V6, V7, V8A–D registered |

---

## Engine State — VERIFIED

- Position sizing: fixed `STOP_PCT = 2%` (config fallback)
- Stop placement: reads `stop_loss_long`/`stop_loss_short` from signal df if present
- Sizing: uses fixed 2% unless `use_atr_sizing = True` in params
- Trail logic: two-phase dynamic trail (normal + tight)
- MTM equity: bar-by-bar, used for DD, Sharpe, Sortino
- Sharpe/Sortino: daily resampled MTM, `sqrt(365)`
- TP Hits counter: counts all exit reasons starting with `tp`
- Parent trade stats: `trades_parent.csv` saved per coin folder

---

## Strategy State — VERIFIED

- Signal: EMA16 cross on 4h candles
- Filter: RSI 52–65 long, 35–48 short
- Stop columns: `stop_loss_long = close - ATR(14) × atr_stop_mult`
- Stop columns: `stop_loss_short = close + ATR(14) × atr_stop_mult`
- Written only when `atr_stop_mult` present in params
- Trail attrs: passed via `df.attrs` from params
- `use_atr_sizing` attr: passed via `df.attrs` from params

---

## Version Hierarchy

| Version | Status | Key Change |
|---------|--------|------------|
| V4 | Archived | Fixed 2% stop, scaled exits 40/30/30 |
| V5 | Archived reference | ATR 2.5× in params (was not wired — now documented) |
| V6 | Rejected | Scaled exits 1.5/2.5/4.0% — cut winners |
| V7 | Archived baseline | Dynamic trail tight — fixed 2% stop |
| V8A | **Active baseline** | ATR×0.7 stop placement, fixed 2% sizing |
| V8B | Rejected | ATR×0.7 + adaptive sizing — DD blowup on BTC/BNB |
| V8C | Rejected (partial) | ATR×0.5 — too tight on BTC/BNB/ETH |
| V8D | Rejected | ATR×1.0 — too wide, returns diluted |

---

## Verified Baseline Results — EMA16 V8A

### Bull / Correction — 2024-03-23 → 2026-03-23

| Coin | Return | Sharpe | Sortino | Max DD | Win Rate |
|------|--------|--------|---------|--------|----------|
| PEPE | +706.7% | 7.79 | 13.40 | -3.56% | 82.4% |
| SOL | +199.5% | 6.70 | 8.22 | -3.21% | 76.8% |
| AAVE | +266.8% | 6.29 | 9.56 | -2.83% | 76.5% |
| LINK | +234.5% | 6.26 | 9.38 | -4.36% | 77.4% |
| DOGE | +198.1% | 5.99 | 9.98 | -3.12% | 75.8% |
| ETH | +105.3% | 4.91 | 6.22 | -3.24% | 66.5% |
| XRP | +118.6% | 4.65 | 6.68 | -3.77% | 67.3% |
| BTC | +23.7% | 2.41 | 2.78 | -3.33% | 60.8% |
| BNB | +25.5% | 2.08 | 2.88 | -3.30% | 59.0% |

### Bear — 2022-03-28 → 2023-10-01 (V8A wins 9/9)

| Coin | Return | Sharpe | Max DD |
|------|--------|--------|--------|
| SOL | +215.4% | 7.32 | -3.24% |
| LINK | +129.4% | 6.40 | -2.25% |
| AAVE | +155.2% | 6.12 | -2.93% |
| PEPE | +49.0% | 6.98 | -1.81% |
| ETH | +60.8% | 4.94 | -3.51% |
| DOGE | +90.1% | 4.47 | -2.75% |
| XRP | +75.5% | 3.61 | -3.62% |
| BNB | +31.2% | 3.18 | -2.61% |
| BTC | +27.9% | 2.94 | -2.61% |

### Chop — 2024-03-04 → 2024-10-28 (V8A wins 7/9)

| Coin | Return | Sharpe | Max DD |
|------|--------|--------|--------|
| PEPE | +127.0% | 7.94 | -5.39% |
| AAVE | +44.2% | 6.55 | -2.62% |
| SOL | +37.9% | 5.95 | -3.21% |
| DOGE | +49.1% | 5.65 | -2.50% |
| ETH | +18.6% | 3.95 | -3.24% |
| LINK | +31.5% | 3.95 | -2.33% |
| BTC | +11.6% | 3.65 | -1.98% |
| XRP | +19.1% | 3.26 | -3.77% |
| BNB | +3.8% | 1.11 | -2.85% |

---

## V8A vs V7 Score

| Period | V8A wins | V7 wins |
|--------|----------|---------|
| Bull 2yr | 8/9 | 1/9 |
| Bear 2022 | 9/9 | 0/9 |
| Chop 2024 | 7/9 | 2/9 |
| **Total** | **24/27** | **3/27** |

---

## Coin Tier Ranking — VERIFIED

| Tier | Coins | Evidence |
|------|-------|----------|
| T1 — Elite | PEPE, SOL, AAVE, DOGE | Strong in all 3 regimes |
| T2 — Solid | LINK, ETH, XRP | Good in trend, acceptable in chop |
| Monitor | BTC, BNB | Low Sharpe but V8A improves DD vs V7 |
| Low sample | HYPE | 9 trades only — data starts Nov 2024 |

---

## Known Open Issues

| Issue | Status | Notes |
|-------|--------|-------|
| Adaptive sizing not yet live | Intentional | V8B/C/D tested and rejected — too risky on BTC/BNB |
| Per-coin ATR multiplier | Future V10 | V8C works on T1 but blows up T2/cut coins |
| Cooldown after stop loss | Not tested | Next experiment — V9 |
| Walk-forward validation | Not done | Needed before live deployment |

---

## Architecture Rules — FROZEN

**Strategy owns:**
- Indicator logic (EMA, RSI, ATR)
- Signal generation
- Stop price columns (`stop_loss_long`, `stop_loss_short`)
- Trail params and `use_atr_sizing` via `df.attrs`
- TP levels via `df.attrs`

**Engine owns:**
- Generic execution
- Reading stop columns from strategy
- Position sizing (from stop distance if `use_atr_sizing=True`, else fixed `STOP_PCT`)
- MTM equity tracking
- Reporting

**To add a new experiment:**
1. Create `params_vN.py`
2. Add entry to `registry.py`
3. Run `--strategy EMA16_VN --tag description`
4. Do not touch `engine.py` or `strategy.py`

---

## Next Planned Tests

| Priority | Test | Type |
|----------|------|------|
| 1 | V9 — Cooldown after stop loss | params only |
| 2 | Walk-forward V8A | validation |
| 3 | Per-coin ATR multiplier (V10) | params + registry |
| 4 | Whitelist — remove BTC/BNB | config change |

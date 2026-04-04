# crypto-algo-bot — Baseline Freeze
## EMA16 V8A — Production Ready
**Date:** 2026-03-23  
**Previous baseline:** EMA16 V7  
**Status:** FROZEN — WALK-FORWARD VALIDATED — READY FOR PAPER TRADING

---

## Active Files

| File | Path | Role |
|------|------|------|
| `engine.py` | `backtest/engine.py` | Execution engine — trail tight + ATR stop column reading |
| `strategy.py` | `strategies/ema16/strategy.py` | Signal logic — ATR stop columns + trail attrs from params |
| `params_v8a.py` | `strategies/ema16/params_v8a.py` | Frozen — active baseline |
| `params_v7.py` | `strategies/ema16/params_v7.py` | Frozen — archived reference |
| `registry.py` | `strategies/registry.py` | V4–V8D registered |

---

## Active Whitelist

| Coin | Tier | WF verdict |
|------|------|------------|
| PEPE | T1 | ✓ Pass — Sharpe 7.56–7.81 across all windows |
| SOL | T1 | ✓ Pass — Sharpe 6.34–7.31, no decay |
| AAVE | T1 | ✓ Pass — best DD profile, never above -3% |
| DOGE | T1 | ✓ Pass — 2023 dip recovers strongly |
| LINK | T2 | ✓ Pass — consistent, minor 2024 dip |
| ETH | T2 | ~ Conditional — works in trend, degrades in sideways |
| XRP | T2 | ✓ Pass — stable 3.26–4.77 range |
| BTC | ❌ Removed | ✗ Declining — Sharpe 4.26→1.84→2.67→1.31 |
| BNB | ❌ Removed | ✗ Declining — never recovers after 2022 |

**Run command with active whitelist:**
```bash
/Users/javierlepianireyes/miniconda3/bin/python backtest/engine.py --strategy EMA16_V8A --tag <tag> --coins PEPE SOL AAVE DOGE LINK ETH XRP
```

---

## Strategy Parameters — FROZEN

```python
ema_period:          16
rsi_period:          14
rsi_long_min:        52
rsi_long_max:        65
rsi_short_min:       35
rsi_short_max:       48
atr_period:          14
atr_stop_mult:       0.7
use_atr_sizing:      False
trail_trigger:       0.005
trail_offset:        0.003
trail_tight_trigger: 0.03
trail_tight_offset:  0.002
risk_pct:            0.005
```

---

## Version Hierarchy

| Version | Status | Key Change |
|---------|--------|------------|
| V4 | Archived | Fixed 2% stop, scaled exits 40/30/30 |
| V5 | Archived | ATR params — was not wired in engine |
| V6 | Rejected | Scaled exits — cut winners |
| V7 | Archived baseline | Dynamic trail tight, fixed 2% stop |
| V8A | **Active baseline ✓** | ATR×0.7 stop placement, fixed 2% sizing |
| V8B | Rejected | ATR×0.7 + adaptive sizing — DD blowup BTC/BNB |
| V8C | Rejected | ATR×0.5 — too tight on low-ATR coins |
| V8D | Rejected | ATR×1.0 — too wide, returns diluted |

---

## Walk-Forward Validation — 4 Independent Yearly Windows

### Sharpe by year

| Coin | 2022 | 2023 | 2024 | 2025 | Verdict |
|------|------|------|------|------|---------|
| PEPE | — | 7.69 | 7.56 | 7.81 | ✓ Rock solid |
| SOL | 7.31 | 6.53 | 6.34 | 7.00 | ✓ Consistent |
| LINK | 7.35 | 6.61 | 5.43 | 7.43 | ✓ Consistent |
| AAVE | 6.89 | 5.60 | 5.91 | 6.53 | ✓ Consistent |
| DOGE | 5.62 | 3.29 | 5.01 | 6.59 | ✓ 2023 dip recovers |
| ETH | 8.18 | 2.26 | 3.01 | 5.22 | ~ Trend-dependent |
| XRP | 4.75 | 3.26 | 4.38 | 4.77 | ✓ Stable |
| BTC | 4.26 | 1.84 | 2.67 | 1.31 | ✗ Declining — removed |
| BNB | 4.27 | 1.82 | 2.09 | 2.05 | ✗ Declining — removed |

### Worst DD per coin across all windows

| Coin | Worst DD | Year |
|------|----------|------|
| PEPE | -5.38% | 2024 |
| SOL | -3.24% | 2022 |
| LINK | -4.36% | 2025 |
| AAVE | -2.93% | 2022 |
| DOGE | -3.24% | 2023 |
| ETH | -3.90% | 2024 |
| XRP | -3.77% | 2024 |

No coin exceeds -5.5% DD in any single year.

---

## Full Backtest Results — V8A Active Whitelist

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

### Bear — 2022-03-28 → 2023-10-01

| Coin | Return | Sharpe | Max DD |
|------|--------|--------|--------|
| SOL | +215.4% | 7.32 | -3.24% |
| LINK | +129.4% | 6.40 | -2.25% |
| AAVE | +155.2% | 6.12 | -2.93% |
| PEPE | +49.0% | 6.98 | -1.81% |
| ETH | +60.8% | 4.94 | -3.51% |
| DOGE | +90.1% | 4.47 | -2.75% |
| XRP | +75.5% | 3.61 | -3.62% |

### Chop — 2024-03-04 → 2024-10-28

| Coin | Return | Sharpe | Max DD |
|------|--------|--------|--------|
| PEPE | +127.0% | 7.94 | -5.39% |
| AAVE | +44.2% | 6.55 | -2.62% |
| SOL | +37.9% | 5.95 | -3.21% |
| DOGE | +49.1% | 5.65 | -2.50% |
| ETH | +18.6% | 3.95 | -3.24% |
| LINK | +31.5% | 3.95 | -2.33% |
| XRP | +19.1% | 3.26 | -3.77% |

---

## Cooldown Analysis — REJECTED

- Zero consecutive SL sequences on all coins tested
- After SL hit: next trade wins 77–83% of the time
- Simulated cooldown costs money — not warranted

---

## Architecture Rules — FROZEN

**Strategy owns:** EMA/RSI/ATR logic, signal generation, stop columns, trail attrs  
**Engine owns:** Generic execution, stop reading, sizing, MTM equity, reporting  

**To add a new experiment:**
1. Create `params_vN.py`
2. Add entry to `registry.py`
3. Run with `--coins PEPE SOL AAVE DOGE LINK ETH XRP`
4. Do not touch `engine.py` or `strategy.py`

---

## Paper Trading Setup

**Exchange:** Hyperliquid perpetuals  
**Coins:** PEPE, SOL, AAVE, DOGE, LINK, ETH, XRP  
**Starting capital:** $500–1000 recommended  
**Risk per trade:** 0.5% of equity  
**Leverage:** 5×  
**Timeframe:** 5m candles → 4h signals  

**What to monitor:**
- Signal timing vs backtest entry times
- Fill quality vs close price
- Stop execution accuracy
- Position size calculation from live equity

**Success criteria after 30 days:**
- Live Sharpe within 20% of backtest Sharpe
- No runaway losses on any single coin
- Stop hits within 0.1% of target price

---

## Next Steps

| Priority | Task |
|----------|------|
| 1 | Paper trade 30 days |
| 2 | Compare live vs backtest metrics |
| 3 | Per-coin ATR multiplier tuning (V9) |
| 4 | Walk-forward on 7-coin whitelist only |

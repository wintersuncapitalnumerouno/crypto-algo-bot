# StochVol V1 — Strategy Research Session
## 2026-03-25
**Status:** Built, backtested, promising — needs walk-forward validation before going live

---

## Strategy Design

**Signal (4h candles resampled from 5m):**
- Entry: Stochastic(14,3,3) %K crosses %D
- Long: %K crosses above %D
- Short: %K crosses below %D
- Volume filter: current volume ≥ 0.7× 20-period average (blocks low-volume entries)

**Position sizing — volume scaled:**
- Base: ATR(14) × 0.7 stop placement (same as V8A)
- Volume multiplier: scales position size 1×–2× based on volume ratio
- Higher volume = larger position (capped at 2×)

**Exit — two mechanisms:**
- Two-phase trail stop: activates at +0.5%, tightens to 0.2% at +3% (same as V8A)
- Volume dry-up partial exit: close 60% of position if volume drops below 50% of average while in profit

---

## Files

| File | Path |
|------|------|
| Strategy | `strategies/stochvol/strategy.py` |
| Params | `strategies/stochvol/params_v1.py` |
| Init | `strategies/stochvol/__init__.py` |
| Engine | `backtest/engine.py` (patched: vol sizing + vol dry-up exit) |
| Registry | `strategies/registry.py` (STOCHVOL_V1 added) |

---

## Backtest Results — 2 Year (2024-03-25 → 2026-03-25)

### StochVol V1 vs EMA16 V8A — Head to Head

| Coin | V8A Sharpe | Stoch Sharpe | Winner | V8A DD | Stoch DD |
|------|-----------|-------------|--------|--------|---------|
| PEPE | 7.96 | **8.70** | StochVol ✅ | -2.61% | -7.79% |
| SOL | **6.67** | 6.20 | V8A ✅ | -3.44% | -5.68% |
| AAVE | 6.44 | **7.28** | StochVol ✅ | -3.68% | -6.83% |
| DOGE | 5.97 | **6.07** | StochVol ✅ | -3.13% | -7.72% |
| LINK | **6.17** | 5.83 | V8A ✅ | -4.39% | -6.71% |
| ETH | 4.76 | **5.17** | StochVol ✅ | -3.41% | -4.90% |
| XRP | 4.50 | **5.15** | StochVol ✅ | -3.93% | -6.28% |

**Score: StochVol 5/7, V8A 2/7 on Sharpe**

### Full History Results (StochVol V1)

| Coin | Return | Sharpe | Sortino | Max DD | Win Rate |
|------|--------|--------|---------|--------|----------|
| SOL | +37,169% | 8.01 | 24.29 | -8.27% | 84.0% |
| AAVE | +19,796% | 7.33 | 18.36 | -4.58% | 81.6% |
| DOGE | +13,001% | 6.32 | 20.12 | -7.80% | 80.9% |
| LINK | +11,810% | 7.40 | 19.83 | -6.05% | 80.8% |
| ETH | +2,388% | 6.80 | 14.28 | -5.13% | 78.5% |
| XRP | +3,565% | 5.55 | 12.53 | -6.83% | 78.2% |
| PEPE | +228% | 6.00 | 14.83 | -7.80% | 84.4% |

---

## Verdict

**StochVol is a serious candidate to replace or complement V8A.**

Strengths:
- Higher Sharpe on 5/7 coins
- Higher win rates across all coins
- Dramatically higher returns (volume sizing compounds well)
- Better Sortino ratios — upside/downside asymmetry is excellent

Weaknesses:
- Higher drawdown — avg 6.5% vs V8A avg 3.5%
- Still needs rolling walk-forward validation
- Volume dry-up exit contribution not yet isolated

**V8A remains the live baseline until walk-forward confirms StochVol out-of-sample.**

---

## Pending Research

1. **Rolling walk-forward** — 12m train / 3m test windows (4 periods over 2 years)
2. **Signal isolation** — test Stochastic cross alone (no volume sizing, no vol dry-up) to isolate edge source
3. **DD reduction** — can we tighten the ATR multiplier (0.5×?) to reduce drawdown without killing returns?
4. **Coin whitelist** — does StochVol work on BTC/BNB where V8A failed?

---

## How to Run

```bash
# Exploration backtest
/Users/javierlepianireyes/miniconda3/bin/python backtest/engine.py --strategy STOCHVOL_V1 --tag <tag> --coins PEPE SOL AAVE DOGE LINK ETH XRP

# Compare vs V8A
/Users/javierlepianireyes/miniconda3/bin/python backtest/engine.py --strategy STOCHVOL_V1 EMA16_V8A --tag <tag> --coins PEPE SOL AAVE DOGE LINK ETH XRP --phase validation
```

---

## Engine Changes (backtest/engine.py)

Three additions for StochVol:

**1. New attrs read:**
```python
vol_dry_threshold = df_signals.attrs.get("vol_dry_threshold", None)
vol_dry_close_pct = df_signals.attrs.get("vol_dry_close_pct", None)
vol_size_min      = df_signals.attrs.get("vol_size_min", 1.0)
vol_size_max      = df_signals.attrs.get("vol_size_max", 1.0)
```

**2. Volume position sizing:**
```python
vol_ratio_entry   = float(row.get("vol_ratio", 1.0) or 1.0)
vol_mult          = min(max(vol_ratio_entry, vol_size_min), vol_size_max)
position_size_usd = (dollar_risk / actual_stop_pct) * vol_mult
```

**3. Volume dry-up partial exit:**
- Triggers if `vol_ratio < vol_dry_threshold` AND position is in profit
- Closes `vol_dry_close_pct` of remaining position
- Only triggers if `remaining_frac > 0.4` (prevents tiny residual positions)
- Logged as `exit_reason = "vol_dry_partial"`

**These changes are backward compatible — EMA16 strategies unaffected (attrs default to 1.0/None).**

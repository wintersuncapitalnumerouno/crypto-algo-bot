# Release Discipline — StochVol

## Architecture

```
Wallet 2 (control)  →  executor_stochvol.py     →  signal_engine_stochvol.py     →  params_v4.py
Wallet 1 (candidate) →  executor_stochvol_v5_candidate.py  →  signal_engine_v5_candidate.py  →  params_v5_candidate.py
```

Both wallets share: stop logic (Fixed 2%), trail params, leverage, coin basket, risk sizing.
Only difference: entry_window (4 vs 3) and vol_min_ratio (0.2 vs 0.3).

## Rules

1. **Production files are read-only** except for critical bug fixes.
2. **Candidate files are self-contained** — no shared imports with production signal engine.
3. **One variable per test.** Do not bundle entry + stop + regime changes.
4. **No promotion without data.** Minimum 2 weeks of live comparison.
5. **Rollback is always one command.**

## Current State

| Wallet | Version | Executor | Status |
|---|---|---|---|
| Wallet 2 | V4 (production) | executor_stochvol.py | LIVE — do not modify |
| Wallet 1 | V5-candidate | executor_stochvol_v5_candidate.py | CANDIDATE |

## V5 Candidate Changes

| Param | V4 (control) | V5 (candidate) |
|---|---|---|
| stoch_k | 14 | 14 |
| entry_window | 3 | **4** |
| vol_min_ratio | 0.3 | **0.2** |
| STOP_PCT | 0.02 | 0.02 |
| trail params | unchanged | unchanged |
| leverage | unchanged | unchanged |

## Deploy Candidate

```bash
git add -A && git commit -m "deploy V5 candidate to Wallet 1"
git push
ssh root@89.167.76.184 "cd /root/crypto-algo-bot && bash deploy_candidate.sh"
```

## Verify Candidate

```bash
ssh root@89.167.76.184 "grep 'V5-candidate\|entry_window=4\|vol_min_ratio=0.2' /root/crypto-algo-bot/live/stochvol2.log | tail -5"
ssh root@89.167.76.184 "cd /root/crypto-algo-bot && /root/miniconda3/bin/python live/ops_check.py"
```

## Rollback

```bash
ssh root@89.167.76.184 "cd /root/crypto-algo-bot && bash rollback_candidate.sh"
```

## Promotion Criteria

Before promoting V5 candidate to both wallets, ALL of these must pass:

| # | Metric | Condition | How to Check |
|---|---|---|---|
| 1 | Runtime | >= 2 weeks without crash | ops_check.py, service uptime |
| 2 | Trades | Wallet 1 trades >= Wallet 2 trades | trades CSV row count |
| 3 | Win rate | Within 5% of Wallet 2 | trades CSV analysis |
| 4 | No blowup | No single-coin DD exceeding historical | log review |
| 5 | Execution | No fill anomalies, no slippage issues | log review |
| 6 | Regime logs | Data collecting cleanly | grep Regime in logs |
| 7 | PnL | Not materially worse than control | equity comparison |

## Promotion Procedure

1. Confirm all criteria above
2. Create `params_v5.py` (copy of params_v5_candidate.py)
3. Update production signal engine to use params_v5
4. Run `deploy.sh` (restarts both wallets)
5. Remove candidate files
6. Update this doc

## Files

| File | Role |
|---|---|
| `live/executor_stochvol.py` | Production — Wallet 2 (control) |
| `live/executor_stochvol_2.py` | Production — Wallet 1 (when not testing) |
| `live/executor_stochvol_v5_candidate.py` | Candidate — Wallet 1 (during test) |
| `live/signal_engine_stochvol.py` | Production signal engine (V4 params) |
| `live/signal_engine_v5_candidate.py` | Candidate signal engine (V5 params) |
| `strategies/stochvol/params_v4.py` | V4 production params |
| `strategies/stochvol/params_v5_candidate.py` | V5 candidate params |
| `deploy.sh` | Deploy production (both wallets) |
| `deploy_candidate.sh` | Deploy candidate (Wallet 1 only) |
| `rollback_candidate.sh` | Revert Wallet 1 to production |

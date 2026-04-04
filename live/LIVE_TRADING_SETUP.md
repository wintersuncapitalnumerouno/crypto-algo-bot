# crypto-algo-bot — Live Trading Setup
## Status: LIVE on Hyperliquid Mainnet
**Date:** 2026-03-24  
**Account:** 0x9b808E...BD94  
**Equity:** $68.39 USDC  

---

## Bot Files

| File | Path | Status |
|------|------|--------|
| `data_feed.py` | `live/data_feed.py` | ✅ Working |
| `signal_engine.py` | `live/signal_engine.py` | ✅ Working |
| `executor.py` | `live/executor.py` | ✅ Working |

---

## Configuration

```python
PAPER_MODE   = False
INITIAL_CAP  = 50.0       # reference only — reads live equity
RISK_PCT     = 0.005      # 0.5% per trade
STOP_PCT     = 0.02       # 2% fixed sizing reference
LEVERAGE     = 5
LOOP_SECONDS = 300        # runs every 5 minutes
COINS        = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]
```

---

## Coin Mapping — Backtest vs Hyperliquid

| Backtest | Hyperliquid | szDecimals |
|----------|-------------|------------|
| PEPE | kPEPE | 0 |
| SOL | SOL | 2 |
| AAVE | AAVE | 2 |
| DOGE | DOGE | 0 |
| LINK | LINK | 1 |
| ETH | ETH | 4 |
| XRP | XRP | 0 |

---

## Account Setup — Lessons Learned

**Unified account:** Hyperliquid unified account stores USDC in spot but it's tradeable for perps. The equity API requires `spotClearinghouseState` not `clearinghouseState` for unified accounts.

**API wallet vs main wallet:**
- `HL_PRIVATE_KEY` = API wallet private key (signs orders, cannot withdraw)
- `HL_WALLET_ADDRESS` = main wallet address (where funds live, what bot reads for equity)

**Order placement:** Hyperliquid SDK requires a price even for market orders. Use IOC limit with 1% buffer (buy at mid×1.01, sell at mid×0.99) to guarantee fill.

---

## How to Start the Bot

**Foreground (see logs in terminal):**
```bash
cd /Users/javierlepianireyes/Desktop/crypto-algo-bot
/Users/javierlepianireyes/miniconda3/bin/python live/executor.py
```

**Background (keeps running after terminal closes):**
```bash
cd /Users/javierlepianireyes/Desktop/crypto-algo-bot
nohup /Users/javierlepianireyes/miniconda3/bin/python live/executor.py > live/trading.log 2>&1 &
echo $!
```
Save the PID number printed.

**Watch logs anytime:**
```bash
tail -f /Users/javierlepianireyes/Desktop/crypto-algo-bot/live/trading.log
```

**Stop the bot:**
```bash
kill <PID>
```

---

## Laptop Setup (for travel)

Conda already installed on MacBook Air. Dependencies installed.

**Install dependencies if needed:**
```bash
/Users/javierlepianireyes/miniconda3/bin/pip install hyperliquid-python-sdk python-dotenv eth-account requests pandas tabulate
```

**Copy `.env` manually** (do not rely on iCloud for security):
```
HL_PRIVATE_KEY=0x...api_wallet_private_key (66 chars)...
HL_WALLET_ADDRESS=0x9b808E...BD94 (main wallet)
```

**Only run on ONE machine at a time** — duplicate orders otherwise.

**Before switching machines:**
1. Kill bot on current machine: `kill <PID>`
2. Start bot on new machine

---

## Monitoring Without Terminal

- Watch live trades, positions, PnL: **app.hyperliquid.xyz → Portfolio**
- Watch bot logs: `tail -f live/trading.log`
- Bot runs every 5 minutes — checks all 7 coins each loop

---

## What the Bot Does Each Loop

1. Fetches 2500 × 5m candles per coin from Hyperliquid
2. Resamples to 4h, runs EMA16 + RSI + ATR (V8A params)
3. If signal + RSI filter passes → enters position
4. If in trade → updates trailing stop
5. If stop hit or opposite signal → exits position
6. Logs everything to `live/trading.log`

---

## Known Issues Fixed

| Issue | Fix |
|-------|-----|
| Equity showed $0.00 | Unified account needs `spotClearinghouseState` endpoint |
| Wrong wallet address | `HL_WALLET_ADDRESS` must be main wallet, not API wallet |
| Order placement error | IOC limit order with 1% price buffer instead of pure market |
| Private key length error | Key must be exactly 66 chars (0x + 64 hex) |

---

## Strategy Running: EMA16 V8A

- ATR×0.7 stop placement, fixed 2% sizing
- Dynamic trail: 0.3% normal, 0.2% above +3% profit  
- Walk-forward validated 2022–2025
- Whitelist: PEPE, SOL, AAVE, DOGE, LINK, ETH, XRP

Full strategy details: `BASELINE_FREEZE_V8A_20260323.md`

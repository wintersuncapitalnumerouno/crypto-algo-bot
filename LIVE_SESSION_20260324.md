# crypto-algo-bot — Live Trading Session
## 2026-03-24 — First Live Trades
**Status:** LIVE and running on Hyperliquid mainnet  
**Account:** 0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94  
**Equity:** ~$68 USDC  
**Strategy:** EMA16 V8A  

---

## What We Built Today

Three live trading files in `live/`:

| File | Purpose |
|------|---------|
| `data_feed.py` | Fetches 2500 × 5m candles per coin from Hyperliquid |
| `signal_engine.py` | Runs V8A strategy on live candles, returns signals |
| `executor.py` | Places orders, manages stops, tracks positions |

---

## How to Start the Bot

**Foreground (see logs):**
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

**Stop the bot:**
```bash
pkill -f executor.py
```

**Watch logs:**
```bash
tail -f live/trading.log
```

---

## Bugs Fixed Today

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Equity showed $0.00 | Wrong wallet address in .env | `HL_WALLET_ADDRESS` must be main wallet, not API wallet |
| Equity showed $3.35 | `clearinghouseState.accountValue` = margin used, not total | Read `spotClearinghouseState` USDC `total` instead |
| Invalid price error | Generic Python rounding invalid for Hyperliquid | 5 significant figures + max `(6 - szDecimals)` decimals using `Decimal` |
| Order must have min $10 | ETH position size too small at $68 equity | Check `size * price >= $11` before placing |
| Position lost on restart | Bot didn't sync existing positions on startup | `sync_positions_on_startup()` reads open positions from exchange |
| Two executor files | Multiple patch sessions created duplicates | Clean rebuild of single `executor.py` |

---

## Account Setup — Key Facts

**Hyperliquid unified account:**
- USDC lives in spot account
- Tradeable for perps without transfer
- `clearinghouseState.accountValue` = margin used (NOT total equity)
- `spotClearinghouseState.balances[USDC].total` = real total equity

**API wallet vs main wallet:**
- `HL_PRIVATE_KEY` = API wallet private key (signs orders, cannot withdraw)
- `HL_WALLET_ADDRESS` = main wallet address (where funds live)

**Coin name mapping:**
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

## First Live Trades

| Coin | Side | Entry | Size | Status |
|------|------|-------|------|--------|
| XRP | Short | $1.4038 | 12 units | Filled |
| SOL | Short | $89.05 | 0.19 units | Filled |
| DOGE | Short | $0.09299 | 184 units | Filled |
| ETH | Short | $2119.6 | 0.008 units | Filled |

Market was in a downtrend on 2026-03-24 — all signals were shorts.

---

## executor.py v2 — Clean Architecture

Four fixes properly implemented:

**1. Equity:**
```python
def get_equity(wallet_address):
    r = requests.post(".../info",
        json={"type": "spotClearinghouseState", "user": wallet_address})
    for b in r.json()["balances"]:
        if b["coin"] == "USDC":
            return float(b["total"])
```

**2. Price rounding:**
```python
def round_perp_price(px, coin):
    # max 5 significant figures + max (6 - szDecimals) decimals
    sz_dec = SZ_DECIMALS[coin]
    max_decimals = max(0, 6 - sz_dec)
    adjusted = Decimal(str(px)).adjusted()
    decimals = min(max_decimals, max(0, 4 - adjusted))
    ...
```

**3. Startup sync:**
```python
def sync_positions_on_startup(self):
    live = get_live_positions(self.wallet)
    for coin, pos in live.items():
        self.positions[coin] = {**pos, "stop_loss": sl}
        self.best_prices[coin] = pos["entry"]
        self.trail_active[coin] = False
```

**4. Min notional:**
```python
if size <= 0 or size * mid < MIN_NOTIONAL:  # MIN_NOTIONAL = 11.0
    log.warning(f"{coin} skipped")
    continue
```

---

## Laptop Setup (for travel)

Conda already installed on MacBook Air. Dependencies installed.
iCloud syncs project folder — `.env` must be copied manually.

**Only run bot on ONE machine at a time.**

Switch machines:
1. `pkill -f executor.py` on current machine
2. Start on new machine

---

## Monitoring

- Live positions and PnL: app.hyperliquid.xyz → Portfolio
- Bot logs: `tail -f live/trading.log`
- Bot runs every 5 minutes, checks all 7 coins

---

## Next Session Priorities

1. Monitor first live trades — verify exits work correctly
2. Check trail stop is activating and tightening
3. Verify equity reads correctly after positions close
4. Consider per-coin position sizing limits

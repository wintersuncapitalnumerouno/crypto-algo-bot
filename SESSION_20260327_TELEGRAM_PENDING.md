# crypto-algo-bot — Session Context
## 2026-03-27 — Telegram Alerts (IN PROGRESS)

---

## Current State

Both bots running on server:
- `trading-bot` (EMA16 V8A) — active ✅
- `stochvol-bot` (StochVol V1) — active ✅

**Mid-session task:** Adding Telegram alerts to both executors.

---

## Telegram Credentials

| Field | Value |
|-------|-------|
| Bot Token | `8421732338:AAFmUMcUG5fLhEiWoThvGQwBvcQTlGFwL3o` |
| Chat ID | `1855483522` |
| Telegram username | @WinterSunCapital |

---

## What Was Done

- ✅ Patched `executor.py` built (with Telegram alerts)
- ✅ Patched `executor_stochvol.py` built (with Telegram alerts)
- ⏳ Files NOT yet deployed to server — interrupted before upload

---

## Next Session — Exact Steps

### 1. SSH into server
```bash
ssh root@89.167.76.184
```

### 2. Stop both bots
```bash
systemctl stop trading-bot stochvol-bot
```

### 3. Upload patched executors from Mac
```bash
# Run on Mac (new terminal tab)
scp /Users/javierlepianireyes/Desktop/crypto-algo-bot/live/executor.py root@89.167.76.184:~/crypto-algo-bot/live/executor.py
scp /Users/javierlepianireyes/Desktop/crypto-algo-bot/live/executor_stochvol.py root@89.167.76.184:~/crypto-algo-bot/live/executor_stochvol.py
```

⚠️ NOTE: The files above are the ORIGINALS (no Telegram).
The patched versions need to be written directly on the server.

### 4. Write patched files on server
Ask Claude to paste the patched executor files directly using `cat > file << 'EOF'` approach.
Both patched files are ready — Claude has them in context.

### 5. Restart both bots
```bash
systemctl start trading-bot stochvol-bot
systemctl status trading-bot stochvol-bot
```

### 6. Verify Telegram works
You should receive:
- "🤖 EMA16 V8A Bot started"  
- "🤖 StochVol V1 Bot started"

---

## What Telegram Alerts Look Like

**Entry:**
```
🟢 EMA16 ENTRY — SOL LONG
Price: 86.15 | Size: 12
Stop: 84.43 | Equity: $71.20
```

**Exit:**
```
✅ EMA16 EXIT — SOL LONG
Reason: signal
Entry: 86.15 → Exit: 91.30
PnL: ✅ $3.24 | Equity: $74.44
```

**Stop hit:**
```
❌ EMA16 EXIT — SOL LONG
Reason: stop
Entry: 86.15 → Exit: 84.43
PnL: ❌ $-1.82 | Equity: $69.38
```

---

## Server Details

| Field | Value |
|-------|-------|
| IP | 89.167.76.184 |
| SSH | `ssh root@89.167.76.184` |
| Cost | €3.77/mo |

## Key Commands

```bash
systemctl status trading-bot stochvol-bot
systemctl stop trading-bot stochvol-bot
systemctl start trading-bot stochvol-bot
tail -f ~/crypto-algo-bot/live/trading.log
tail -f ~/crypto-algo-bot/live/stochvol.log
```

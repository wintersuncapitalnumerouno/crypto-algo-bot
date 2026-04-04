# crypto-algo-bot — Server Deployment COMPLETE
## 2026-03-27 — Both Bots Live on Hetzner VPS

---

## Server Details

| Field | Value |
|-------|-------|
| Provider | Hetzner Cloud |
| Server name | Legatus |
| Plan | CX23 — 2 vCPU, 4GB RAM, 40GB SSD |
| Location | Helsinki, EU |
| OS | Ubuntu 24.04 LTS |
| Public IP | **89.167.76.184** |
| Cost | €3.77/mo |

---

## SSH Access

```bash
ssh root@89.167.76.184
```

SSH key: `~/.ssh/id_rsa` (Mac mini)

---

## Bots Running

| Bot | Service | Wallet | Equity | Log |
|-----|---------|--------|--------|-----|
| EMA16 V8A | `trading-bot` | `0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94` | ~$71 USDC | `live/trading.log` |
| StochVol V1 | `stochvol-bot` | `0xb2A1B87B1B91Ad37520594263958cED3948151fF` | ~$48 USDC | `live/stochvol.log` |

Both bots:
- Run every 5 minutes across PEPE, SOL, AAVE, DOGE, LINK, ETH, XRP
- Auto-restart on failure (systemd `Restart=on-failure`)
- Auto-start on server reboot (`systemctl enable`)

---

## Server File Structure

```
/root/crypto-algo-bot/
├── .env                          ← Both wallet keys
└── live/
    ├── executor.py               ← EMA16 V8A bot
    ├── executor_stochvol.py      ← StochVol V1 bot
    ├── signal_engine.py          ← V8A signals
    ├── signal_engine_stochvol.py ← StochVol signals
    ├── data_feed.py              ← Candle fetching
    ├── dashboard.py              ← EMA16 terminal dashboard
    ├── dashboard_stochvol.py     ← StochVol terminal dashboard
    ├── trading.log               ← EMA16 bot log
    ├── stochvol.log              ← StochVol bot log
    └── trades_live.csv           ← Trade history
```

---

## .env Structure

```
# EMA16 V8A — existing
HL_PRIVATE_KEY=0x...
HL_WALLET_ADDRESS=0x9b808Eaa...

# StochVol V1 — new wallet
HL_STOCHVOL_PRIVATE_KEY=0x...
HL_STOCHVOL_WALLET_ADDRESS=0xb2A1B...
```

---

## Key Commands (on server)

```bash
# Check both bots status
systemctl status trading-bot
systemctl status stochvol-bot

# Watch live logs
tail -f ~/crypto-algo-bot/live/trading.log
tail -f ~/crypto-algo-bot/live/stochvol.log

# Stop / start / restart
systemctl stop trading-bot
systemctl start trading-bot
systemctl restart trading-bot

systemctl stop stochvol-bot
systemctl start stochvol-bot
systemctl restart stochvol-bot

# Check both running at once
ps aux | grep executor | grep -v grep
```

## Update Bot Files from Mac

```bash
# Upload changed file
scp /Users/javierlepianireyes/Desktop/crypto-algo-bot/live/executor.py root@89.167.76.184:~/crypto-algo-bot/live/executor.py

# Restart after upload
ssh root@89.167.76.184 "systemctl restart trading-bot"
ssh root@89.167.76.184 "systemctl restart stochvol-bot"
```

---

## Pending Next Steps

- [ ] **Telegram bot alerts** — trade notifications on phone for both strategies
- [ ] **StochVol walk-forward validation** — 12m train / 3m test windows before trusting it fully
- [ ] **StochVol V2** — adaptive ATR stops (ATR×0.7 normal, ATR×1.0 high-volume) to reduce DD
- [ ] **Signal isolation** — stoch cross alone vs full StochVol strategy
- [ ] **Web dashboard** — monitor both bots from browser/phone without SSH

---

## Critical Rules

- **Mac bot must be OFF** — both strategies now run on server only
- Never commit `.env` to git
- Only one machine running at a time per strategy
- To switch back to Mac: `systemctl stop trading-bot stochvol-bot` on server first

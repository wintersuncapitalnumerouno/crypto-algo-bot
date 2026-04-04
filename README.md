# 🤖 Crypto Algo Bot — Hyperliquid Scalping System

A beginner-friendly algorithmic trading framework for backtesting and
deploying Momentum + Breakout strategies on Hyperliquid perpetuals.

---

## 📁 Project Structure

```
crypto-algo-bot/
├── README.md              ← You are here
├── requirements.txt       ← All Python libraries to install
├── config.py              ← Your settings (coins, timeframes, etc.)
│
├── data/
│   └── fetch_data.py      ← Downloads OHLCV candles from Hyperliquid
│
├── strategies/
│   ├── momentum.py        ← Momentum / Trend Following strategy
│   └── breakout.py        ← Breakout / Volatility strategy
│
├── backtest/
│   └── engine.py          ← Runs backtests, compares strategies
│
├── analysis/
│   └── report.py          ← Sharpe ratio, drawdown, win rate, charts
│
└── live/
    └── trader.py          ← Live execution on Hyperliquid (Phase 5)
```

---

## 🚀 Setup (Do This First)

### Step 1 — Make sure Python is installed
Open your terminal and run:
```bash
python3 --version
```
You should see Python 3.9 or higher. If not, download from https://python.org

### Step 2 — Create a virtual environment (keeps things clean)
```bash
cd crypto-algo-bot
python3 -m venv venv

# On Mac/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

You'll see `(venv)` appear in your terminal. That means it worked.

### Step 3 — Install all libraries
```bash
pip install -r requirements.txt
```
This will take 1-2 minutes. That's normal.

### Step 4 — Fetch your first data
```bash
python data/fetch_data.py
```

You should see candles downloading and a confirmation message.
Data gets saved to `data/candles/` as CSV files.

---

## 📊 Phase Progress

- [x] **Phase 1** — Environment + Data Pipeline  ← YOU ARE HERE
- [ ] **Phase 2** — Signal Engineering
- [ ] **Phase 3** — Backtesting (Momentum + Breakout)
- [ ] **Phase 4** — Performance Evaluation
- [ ] **Phase 5** — Live on Hyperliquid Testnet → Mainnet

---

## ❓ Troubleshooting

**"command not found: python3"** → Use `python` instead of `python3`

**"No module named X"** → Make sure your venv is active (`source venv/bin/activate`)
and run `pip install -r requirements.txt` again

**Network error fetching data** → Hyperliquid's API is public, no key needed.
Check your internet connection.

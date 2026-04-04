# =============================================================
# config.py — Central settings for the entire bot
# =============================================================
#
# WHAT LIVES HERE:
#   - Asset definitions
#   - Timeframes, data paths, API endpoints
#   - Backtest capital & fees
#   - Risk management globals
#   - Results storage, logging
#
# WHAT DOES NOT LIVE HERE:
#   - Strategy parameters  ← each strategy owns its own params.py
# =============================================================

# =============================================================
# ASSETS — the ONLY place you edit to add/remove a coin
# =============================================================
ASSETS = {
    # ── Core / majors ─────────────────────────────────────────
    "BTC": {
        "start":  "2019-09-08",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance BTC/USDT perpetual launch",
    },
    "ETH": {
        "start":  "2019-11-27",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance ETH/USDT perpetual launch",
    },
    "SOL": {
        "start":  "2020-09-14",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance SOL/USDT perpetual launch",
    },
    "LINK": {
        "start":  "2020-01-06",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance LINK/USDT perpetual launch",
    },
    "BNB": {
        "start":  "2020-02-10",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance BNB/USDT perpetual launch",
    },
    "XRP": {
        "start":  "2020-01-06",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance XRP/USDT perpetual launch",
    },
    # ── Hyperliquid native ────────────────────────────────────
    "HYPE": {
        "start":  "2024-11-01",
        "source": "hyperliquid",
        "type":   "perp",
        "note":   "Hyperliquid native — 17 day API cap",
    },
    # ── Meme / high-beta ──────────────────────────────────────
    "DOGE": {
        "start":  "2020-07-10",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance DOGE/USDT perpetual launch",
    },
    "PEPE": {
        "start":  "2023-05-27",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance PEPE/USDT perpetual launch",
    },
    # ── DeFi ──────────────────────────────────────────────────
    "AAVE": {
        "start":  "2021-01-01",
        "source": "binance",
        "type":   "perp",
        "note":   "Binance AAVE/USDT perpetual launch",
    },
}

# Derived automatically — never edit this manually
COINS = list(ASSETS.keys())

# -------------------------------------------------------------
# TIMEFRAMES
# -------------------------------------------------------------
DOWNLOAD_TIMEFRAMES = ["5m"]
BACKTEST_TIMEFRAMES = ["5m"]
TIMEFRAMES          = DOWNLOAD_TIMEFRAMES
PRIMARY_TIMEFRAME   = "5m"

# -------------------------------------------------------------
# DATA
# -------------------------------------------------------------
LOOKBACK_DAYS_DEFAULT = 365
DATA_DIR              = "data/candles"
DB_PATH               = "data/market_data.db"

# -------------------------------------------------------------
# HYPERLIQUID API
# -------------------------------------------------------------
HL_API_URL     = "https://api.hyperliquid.xyz/info"
HL_TESTNET_URL = "https://api.hyperliquid-testnet.xyz/info"

# -------------------------------------------------------------
# IBKR — macro data feed
# -------------------------------------------------------------
MACRO_PROVIDER  = "ibkr"
IBKR_HOST       = "127.0.0.1"
IBKR_PORT       = 4001
IBKR_CLIENT_ID  = 1

MACRO_SYMBOLS = {
    "VIX":   {"symbol": "VIX", "secType": "IND", "exchange": "CBOE",  "currency": "USD"},
    "SPX":   {"symbol": "SPX", "secType": "IND", "exchange": "CBOE",  "currency": "USD"},
    "DXY":   {"symbol": "DX",  "secType": "FUT", "exchange": "NYBOT", "currency": "USD", "expiry": "20260316"},
    "US10Y": {"symbol": "ZN",  "secType": "FUT", "exchange": "CBT",   "currency": "USD", "expiry": "20260619"},
    "GLD":   {"symbol": "GLD", "secType": "STK", "exchange": "ARCA",  "currency": "USD"},
}

# -------------------------------------------------------------
# BACKTEST DATE RANGES
# -------------------------------------------------------------
BACKTEST_MODE   = "split"
TRAIN_START     = "2021-01-01"
TRAIN_END       = "2023-12-31"
TEST_START      = "2024-01-01"
TEST_END        = "2024-12-31"
WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS  = 3

# -------------------------------------------------------------
# CAPITAL & FEES
# -------------------------------------------------------------
INITIAL_CAPITAL = 10_000   # USD
TAKER_FEE       = 0.00035  # 0.035% per side
SLIPPAGE        = 0.0005   # 0.05% estimated slippage
LEVERAGE        = 5        # 5x leverage

# -------------------------------------------------------------
# RISK MANAGEMENT
# -------------------------------------------------------------
RISK_PER_TRADE        = 0.05   # Risk 5% of capital per trade
STOP_LOSS_PCT         = 0.01   # Hard stop: 1% from entry
TRAILING_STOP_PCT     = 0.01   # Trailing stop distance: 1%
TRAILING_STOP_TRIGGER = 1.0    # Activate after 1x ATR profit
DAILY_DRAWDOWN_LIMIT  = 0.15   # Halt if down 15% in a day
MAX_HOLD_CANDLES      = 96     # Time stop: 96 x 5m = 8 hours

# -------------------------------------------------------------
# RISK MODEL
# -------------------------------------------------------------
# These two values are the single source of truth for all sizing.
# position_size_usd = (equity * RISK_PCT) / STOP_PCT
# Example: (10000 * 0.005) / 0.02 = 2500 USD position
RISK_PCT = 0.005   # max loss per trade = 0.5% of equity
STOP_PCT = 0.02    # stop distance = 2% from entry price

# -------------------------------------------------------------
# RESULTS STORAGE
# -------------------------------------------------------------
RUN_NAME    = "auto"
RESULTS_DIR = "results"

# -------------------------------------------------------------
# LOGGING
# -------------------------------------------------------------
LOG_DIR   = "logs"
LOG_LEVEL = "INFO"

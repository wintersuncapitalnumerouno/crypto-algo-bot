# =============================================================
# live/trade_logger.py — Centralised trade registry
# =============================================================
#
# WHAT THIS DOES:
#   Single writer for all closed trades across all executors.
#   Produces one canonical CSV (trades_master.csv) with fees
#   deducted, matching backtest engine PnL methodology.
#
# USAGE:
#   from live.trade_logger import record_trade
#   record_trade(strategy="STOCHVOL_V4", bot_id="wallet1", ...)
#
# FEE NOTE:
#   Live fills (avgPx from Hyperliquid) already include slippage,
#   so we only apply TAKER_FEE (0.035% per side).
#   The backtest engine adds SLIPPAGE (0.05%) on top because it
#   simulates exits from candle closes — that distinction is
#   intentional, not a bug.
#
# PNL FORMULA (mirrors backtest/engine.py lines 629, 508-510):
#   adj_entry = entry_price * (1 + fee)      # cost basis
#   long:  pnl_pct = (exit * (1 - fee) - adj_entry) / adj_entry
#   short: pnl_pct = (adj_entry - exit * (1 + fee)) / adj_entry
#   pnl_usd = size_usd * pnl_pct
# =============================================================

import csv
import uuid
from pathlib import Path
from datetime import datetime, timezone

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ── Fee constant ──────────────────────────────────────────────
# Live fills (avgPx) already include slippage — only charge the
# Hyperliquid taker fee.  The backtest adds config.SLIPPAGE on
# top because it simulates exits from candle closes.
LIVE_FEE = config.TAKER_FEE   # 0.035% per side

# ── Paths ─────────────────────────────────────────────────────
MASTER_CSV = Path(__file__).parent / "trades_master.csv"

# ── Canonical schema ──────────────────────────────────────────
FIELDS = [
    "trade_id",
    "strategy",
    "bot_id",
    "coin",
    "direction",
    "timeframe",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "size_usd",
    "stop_loss",
    "take_profit",
    "vol_ratio",
    "leverage",
    "exit_reason",
    "pnl_usd",
    "pnl_pct",
    "fee_usd",
    "duration_min",
    "equity_after",
]


def record_trade(
    strategy: str,
    bot_id: str,
    coin: str,
    direction: str,
    entry_time: datetime,
    exit_time: datetime,
    entry_price: float,
    exit_price: float,
    size_usd: float,
    stop_loss: float,
    take_profit: float,
    exit_reason: str,
    equity_after: float,
    vol_ratio: float = 0.0,
    leverage: int = 5,
    timeframe: str = "5m",
) -> dict:
    """
    Record a closed trade to trades_master.csv.

    entry_price / exit_price are raw Hyperliquid fills (avgPx).
    Fees applied on both sides to match backtest methodology:
      adj_entry = entry * (1 + LIVE_FEE)
      long:  pnl_pct = (exit * (1 - LIVE_FEE) - adj_entry) / adj_entry
      short: pnl_pct = (adj_entry - exit * (1 + LIVE_FEE)) / adj_entry
    """
    duration_min = int((exit_time - entry_time).total_seconds() / 60)

    if direction == "long":
        adj_entry = entry_price * (1 + LIVE_FEE)
        pnl_pct = (exit_price * (1 - LIVE_FEE) - adj_entry) / adj_entry
    else:
        adj_entry = entry_price * (1 - LIVE_FEE)
        pnl_pct = (adj_entry - exit_price * (1 + LIVE_FEE)) / adj_entry

    pnl_usd = size_usd * pnl_pct
    fee_usd = size_usd * LIVE_FEE * 2  # both legs, for reporting

    row = {
        "trade_id":     str(uuid.uuid4())[:8],
        "strategy":     strategy,
        "bot_id":       bot_id,
        "coin":         coin,
        "direction":    direction,
        "timeframe":    timeframe,
        "entry_time":   entry_time.isoformat(),
        "exit_time":    exit_time.isoformat(),
        "entry_price":  round(entry_price, 6),
        "exit_price":   round(exit_price, 6),
        "size_usd":     round(size_usd, 2),
        "stop_loss":    round(stop_loss, 6),
        "take_profit":  round(take_profit, 6),
        "vol_ratio":    round(vol_ratio, 4),
        "leverage":     leverage,
        "exit_reason":  exit_reason,
        "pnl_usd":      round(pnl_usd, 4),
        "pnl_pct":      round(pnl_pct * 100, 4),
        "fee_usd":      round(fee_usd, 4),
        "duration_min":  duration_min,
        "equity_after":  round(equity_after, 2),
    }

    write_header = not MASTER_CSV.exists()
    with open(MASTER_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return row

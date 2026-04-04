#!/usr/bin/env python3
# =============================================================
# live/dashboard.py — Live Trading Dashboard
# =============================================================
# Runs in a separate terminal while the bot runs in background.
# Refreshes every 30 seconds showing:
#   - Equity and bot status
#   - Open positions with live PnL
#   - Recent trades from trading.log
#   - Signal snapshot for all coins
#
# Usage:
#   /Users/javierlepianireyes/miniconda3/bin/python live/dashboard.py
# =============================================================

import os
import sys
import time
import requests
import re
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from live.data_feed import DataFeed, COIN_MAP
from live.signal_engine import SignalEngine

API_URL        = "https://api.hyperliquid.xyz/info"
WALLET_ADDRESS = os.getenv("HL_WALLET_ADDRESS")
REFRESH_SEC    = 30
LOG_FILE       = Path("live/trading.log")

HL_COINS = {k: v for k, v in COIN_MAP.items()}
COINS    = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]

# ── ANSI colors ───────────────────────────────────────────────
G  = "\033[92m"   # green
R  = "\033[91m"   # red
Y  = "\033[93m"   # yellow
B  = "\033[94m"   # blue
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
DIM = "\033[2m"
RST = "\033[0m"
BOLD = "\033[1m"


def clear():
    os.system("clear")


def post(payload):
    try:
        r = requests.post(API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5)
        return r.json()
    except:
        return {}


def get_equity():
    data = post({"type": "spotClearinghouseState", "user": WALLET_ADDRESS})
    for b in data.get("balances", []):
        if b["coin"] == "USDC":
            return float(b["total"])
    return 0.0


def get_positions():
    data = post({"type": "clearinghouseState", "user": WALLET_ADDRESS})
    hl_to_bt = {v: k for k, v in HL_COINS.items()}
    positions = {}
    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        hl_coin = p.get("coin")
        bt_coin = hl_to_bt.get(hl_coin)
        if not bt_coin:
            continue
        szi = float(p.get("szi", 0))
        if szi == 0:
            continue
        positions[bt_coin] = {
            "side":       "LONG" if szi > 0 else "SHORT",
            "size":       abs(szi),
            "entry":      float(p.get("entryPx", 0)),
            "unrealized": float(p.get("unrealizedPnl", 0)),
            "margin":     float(p.get("marginUsed", 0)),
            "liq_price":  float(p.get("liquidationPx", 0) or 0),
            "hl_coin":    hl_coin,
        }
    return positions


def get_mid_prices():
    data = post({"type": "allMids"})
    return {k: float(v) for k, v in data.items()}


def get_recent_trades(n=8):
    """Parse recent completed trades from trading.log."""
    trades = []
    if not LOG_FILE.exists():
        return trades
    try:
        lines = LOG_FILE.read_text().split("\n")
        for line in reversed(lines):
            if "ENTER" in line or "EXIT" in line:
                trades.append(line.strip())
            if len(trades) >= n:
                break
    except:
        pass
    return list(reversed(trades))


def is_bot_running():
    """Check if executor.py is running."""
    try:
        result = os.popen("ps aux | grep executor.py | grep -v grep").read()
        return bool(result.strip())
    except:
        return False


def get_last_loop_time():
    """Get timestamp of last bot loop from log."""
    if not LOG_FILE.exists():
        return "unknown"
    try:
        lines = LOG_FILE.read_text().split("\n")
        for line in reversed(lines):
            if "Loop at" in line:
                match = re.search(r"Loop at (.+)", line)
                if match:
                    return match.group(1).strip()
    except:
        pass
    return "unknown"


def format_pnl(pnl):
    if pnl > 0:
        return f"{G}+${pnl:.4f}{RST}"
    elif pnl < 0:
        return f"{R}-${abs(pnl):.4f}{RST}"
    return f"${pnl:.4f}"


def format_side(side):
    if side == "LONG":
        return f"{G}LONG {RST}"
    return f"{R}SHORT{RST}"


def render(feed, engine):
    clear()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bot_running = is_bot_running()
    last_loop   = get_last_loop_time()
    equity      = get_equity()
    positions   = get_positions()
    mids        = get_mid_prices()

    bot_status = f"{G}● RUNNING{RST}" if bot_running else f"{R}● STOPPED{RST}"

    # ── Header ────────────────────────────────────────────────
    print(f"\n{BOLD}{C}{'═' * 62}{RST}")
    print(f"{BOLD}{C}  EMA16 V8A — Live Dashboard{RST}  {DIM}{now}{RST}")
    print(f"{BOLD}{C}{'═' * 62}{RST}")
    print(f"  {BOLD}Equity:{RST} {G}${equity:.2f} USDC{RST}  │  Bot: {bot_status}  │  Last loop: {DIM}{last_loop}{RST}")
    print()

    # ── Open positions ────────────────────────────────────────
    print(f"{BOLD}{W}  OPEN POSITIONS{RST}")
    print(f"  {DIM}{'─' * 58}{RST}")

    if not positions:
        print(f"  {DIM}No open positions{RST}")
    else:
        print(f"  {DIM}{'Coin':<6} {'Side':<7} {'Entry':>10} {'Now':>10} {'PnL':>12} {'Liq':>10}{RST}")
        for coin, pos in positions.items():
            hl_coin = HL_COINS.get(coin, coin)
            now_price = mids.get(hl_coin, 0)
            upnl = pos["unrealized"]
            pnl_str = format_pnl(upnl)
            side_str = format_side(pos["side"])
            liq = pos["liq_price"]
            print(f"  {BOLD}{coin:<6}{RST} {side_str} {pos['entry']:>10.5f} {now_price:>10.5f} {pnl_str:>12} {R}{liq:>10.4f}{RST}")

    print()

    # ── Signal snapshot ───────────────────────────────────────
    print(f"{BOLD}{W}  SIGNAL SNAPSHOT{RST}")
    print(f"  {DIM}{'─' * 58}{RST}")
    print(f"  {DIM}{'Coin':<6} {'Action':<12} {'RSI':>6} {'Price':>12} {'Candle'}{RST}")

    try:
        for coin in COINS:
            df = feed.get_candles(coin)
            sig = engine.get_signal(coin, df)
            action = sig.get("action")
            rsi = sig.get("rsi", 0)
            price = sig.get("entry_price", 0)
            candle = sig.get("candle_time", "")[:16]

            if action in ("long", "exit_short"):
                action_str = f"{G}{str(action):<12}{RST}"
            elif action in ("short", "exit_long"):
                action_str = f"{R}{str(action):<12}{RST}"
            else:
                action_str = f"{DIM}{str(action):<12}{RST}"

            in_pos = "●" if coin in positions else " "
            print(f"  {in_pos}{coin:<6} {action_str} {rsi:>6.1f} {price:>12.6f} {DIM}{candle}{RST}")
    except Exception as e:
        print(f"  {R}Signal error: {e}{RST}")

    print()

    # ── Recent activity ───────────────────────────────────────
    print(f"{BOLD}{W}  RECENT ACTIVITY{RST}")
    print(f"  {DIM}{'─' * 58}{RST}")
    trades = get_recent_trades(6)
    if not trades:
        print(f"  {DIM}No recent activity{RST}")
    else:
        for t in trades:
            # Color ENTER green, EXIT red
            if "ENTER" in t:
                ts = t.split("INFO")[-1].strip() if "INFO" in t else t
                print(f"  {G}{ts}{RST}")
            elif "EXIT" in t:
                ts = t.split("INFO")[-1].strip() if "INFO" in t else t
                print(f"  {Y}{ts}{RST}")
            else:
                ts = t.split("INFO")[-1].strip() if "INFO" in t else t
                print(f"  {DIM}{ts}{RST}")

    print()
    print(f"  {DIM}Refreshing every {REFRESH_SEC}s — Ctrl+C to exit{RST}")
    print(f"{BOLD}{C}{'═' * 62}{RST}\n")


def main():
    feed   = DataFeed()
    engine = SignalEngine()

    print(f"\n{C}Starting dashboard...{RST}")
    time.sleep(1)

    while True:
        try:
            render(feed, engine)
        except KeyboardInterrupt:
            print(f"\n{Y}Dashboard stopped.{RST}\n")
            break
        except Exception as e:
            print(f"\n{R}Error: {e}{RST}")
        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()

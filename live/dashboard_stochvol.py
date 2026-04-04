#!/usr/bin/env python3
# =============================================================
# live/dashboard_stochvol.py — StochVol V1 Live Dashboard
# =============================================================
# Runs in a separate terminal while the StochVol bot runs.
# Refreshes every 30 seconds showing:
#   - Equity and bot status
#   - Open positions with live PnL
#   - Recent activity from stochvol.log
#   - Signal snapshot for all coins
#
# Usage:
#   /Users/javierlepianireyes/miniconda3/bin/python live/dashboard_stochvol.py
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

from live.data_feed import DataFeed

API_URL = "https://api.hyperliquid.xyz/info"
WALLET_ADDRESS = os.getenv("HL_STOCHVOL_WALLET_ADDRESS")
REFRESH_SEC = 30
LOG_FILE = Path("live/stochvol.log")

COIN_MAP = {
    "PEPE": "kPEPE",
    "SOL": "SOL",
    "AAVE": "AAVE",
    "DOGE": "DOGE",
    "LINK": "LINK",
    "ETH": "ETH",
    "XRP": "XRP",
}
HL_TO_BT = {v: k for k, v in COIN_MAP.items()}
COINS = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]

# ── ANSI colors ───────────────────────────────────────────────
G = "\033[92m"
R = "\033[91m"
Y = "\033[93m"
B = "\033[94m"
C = "\033[96m"
W = "\033[97m"
DIM = "\033[2m"
RST = "\033[0m"
BOLD = "\033[1m"


def clear():
    os.system("clear")


def post(payload: dict) -> dict:
    try:
        r = requests.post(
            API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def get_equity() -> float:
    data = post({"type": "spotClearinghouseState", "user": WALLET_ADDRESS})
    for b in data.get("balances", []):
        if b.get("coin") == "USDC":
            try:
                return float(b.get("total", 0))
            except Exception:
                return 0.0
    return 0.0


def get_positions() -> dict:
    data = post({"type": "clearinghouseState", "user": WALLET_ADDRESS})
    positions = {}

    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        hl_coin = p.get("coin")
        bt_coin = HL_TO_BT.get(hl_coin)
        if not bt_coin:
            continue

        szi = float(p.get("szi", 0))
        if szi == 0:
            continue

        positions[bt_coin] = {
            "side": "LONG" if szi > 0 else "SHORT",
            "size": abs(szi),
            "entry": float(p.get("entryPx", 0)),
            "unrealized": float(p.get("unrealizedPnl", 0)),
            "margin": float(p.get("marginUsed", 0)),
            "liq_price": float(p.get("liquidationPx", 0) or 0),
            "hl_coin": hl_coin,
        }

    return positions


def get_mid_prices() -> dict:
    data = post({"type": "allMids"})
    try:
        return {k: float(v) for k, v in data.items()}
    except Exception:
        return {}


def get_recent_activity(n: int = 8) -> list[str]:
    items = []
    if not LOG_FILE.exists():
        return items

    try:
        lines = LOG_FILE.read_text().split("\n")
        for line in reversed(lines):
            if any(x in line for x in ["📤", "✅ Order", "✅ Exit", "❌ Order", "❌ Exit", "💰 PnL"]):
                items.append(line.strip())
            elif "action=" in line:
                continue
            elif "Sleeping" in line:
                continue
            elif "DEBUG get_equity" in line:
                continue

            if len(items) >= n:
                break
    except Exception:
        pass

    return list(reversed(items))


def is_bot_running() -> bool:
    try:
        result = os.popen("ps aux | grep executor_stochvol.py | grep -v grep").read()
        return bool(result.strip())
    except Exception:
        return False


def get_last_loop_time() -> str:
    if not LOG_FILE.exists():
        return "unknown"

    try:
        lines = LOG_FILE.read_text().split("\n")
        for line in reversed(lines):
            if "Sleeping" in line:
                m = re.match(r"\[(.*?)\]", line)
                if m:
                    return m.group(1) + " UTC"
    except Exception:
        pass

    return "unknown"


def format_pnl(pnl: float) -> str:
    if pnl > 0:
        return f"{G}+${pnl:.4f}{RST}"
    if pnl < 0:
        return f"{R}-${abs(pnl):.4f}{RST}"
    return f"${pnl:.4f}"


def format_side(side: str) -> str:
    if side == "LONG":
        return f"{G}LONG {RST}"
    return f"{R}SHORT{RST}"


def render(feed, engine):
    clear()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bot_running = is_bot_running()
    last_loop = get_last_loop_time()
    equity = get_equity()
    positions = get_positions()
    mids = get_mid_prices()

    bot_status = f"{G}● RUNNING{RST}" if bot_running else f"{R}● STOPPED{RST}"

    print(f"\n{BOLD}{C}{'═' * 66}{RST}")
    print(f"{BOLD}{C}  StochVol V1 — Live Dashboard{RST}  {DIM}{now}{RST}")
    print(f"{BOLD}{C}{'═' * 66}{RST}")
    print(f"  {BOLD}Equity:{RST} {G}${equity:.2f} USDC{RST}  │  Bot: {bot_status}  │  Last loop: {DIM}{last_loop}{RST}")
    print()

    print(f"{BOLD}{W}  OPEN POSITIONS{RST}")
    print(f"  {DIM}{'─' * 62}{RST}")

    if not positions:
        print(f"  {DIM}No open positions{RST}")
    else:
        print(f"  {DIM}{'Coin':<6} {'Side':<7} {'Entry':>12} {'Now':>12} {'PnL':>14} {'Liq':>12}{RST}")
        for coin, pos in positions.items():
            hl_coin = pos["hl_coin"]
            now_price = mids.get(hl_coin, 0.0)
            upnl = pos["unrealized"]
            pnl_str = format_pnl(upnl)
            side_str = format_side(pos["side"])
            liq = pos["liq_price"]

            print(
                f"  {BOLD}{coin:<6}{RST} {side_str} "
                f"{pos['entry']:>12.6f} {now_price:>12.6f} {pnl_str:>14} {R}{liq:>12.6f}{RST}"
            )

    print()

    print(f"{BOLD}{W}  SIGNAL SNAPSHOT{RST}")
    print(f"  {DIM}{'─' * 62}{RST}")
    print(f"  {DIM}{'Coin':<6} {'Action':<10} {'VolRatio':>8} {'K':>7} {'D':>7} {'Candle'}{RST}")

    try:
        for coin in COINS:
            df = feed.get_candles(coin)
            sig = engine.get_signal(coin, df)

            action = sig.get("action")
            vol_ratio = sig.get("vol_ratio", 0.0)
            stoch_k = sig.get("stoch_k", 0.0)
            stoch_d = sig.get("stoch_d", 0.0)
            candle = str(sig.get("candle_time", ""))[:16]

            if action == "long":
                action_str = f"{G}{action:<10}{RST}"
            elif action == "short":
                action_str = f"{R}{action:<10}{RST}"
            else:
                action_str = f"{DIM}{str(action):<10}{RST}"

            in_pos = "●" if coin in positions else " "
            print(
                f"  {in_pos}{coin:<6} {action_str} "
                f"{vol_ratio:>8.2f} {stoch_k:>7.1f} {stoch_d:>7.1f} {DIM}{candle}{RST}"
            )

    except Exception as e:
        print(f"  {R}Signal error: {e}{RST}")

    print()

    print(f"{BOLD}{W}  RECENT ACTIVITY{RST}")
    print(f"  {DIM}{'─' * 62}{RST}")
    activity = get_recent_activity(6)

    if not activity:
        print(f"  {DIM}No recent activity{RST}")
    else:
        for line in activity:
            stripped = line
            if "] " in stripped:
                stripped = stripped.split("] ", 1)[1]

            if "❌" in stripped:
                print(f"  {R}{stripped}{RST}")
            elif "💰 PnL" in stripped:
                print(f"  {Y}{stripped}{RST}")
            elif "✅" in stripped or "📤" in stripped:
                print(f"  {G}{stripped}{RST}")
            else:
                print(f"  {DIM}{stripped}{RST}")

    print()
    print(f"  {DIM}Refreshing every {REFRESH_SEC}s — Ctrl+C to exit{RST}")
    print(f"{BOLD}{C}{'═' * 66}{RST}\n")


def main():
    from live.signal_engine_stochvol import StochVolSignalEngine

    feed = DataFeed()
    engine = StochVolSignalEngine()

    print(f"\n{C}Starting StochVol dashboard...{RST}")
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
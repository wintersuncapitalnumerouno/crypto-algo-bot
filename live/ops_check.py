#!/usr/bin/env python3
# =============================================================
# live/ops_check.py — Lightweight Operator Checklist
# =============================================================
#
# Quick ops status for both StochVol V4 bots.
# Run on the server or via SSH:
#
#   ssh root@89.167.76.184 "cd /root/crypto-algo-bot && python3 live/ops_check.py"
#
# Checks:
#   1. Service status (systemd)
#   2. Positions open (exchange API)
#   3. State file freshness (positions_state, last_entry_candle)
#   4. Last loop time (from logs)
#   5. Reconciliation status (last startup)
#   6. Recent entries/exits
# =============================================================

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv("/root/crypto-algo-bot/.env")

HL_API = "https://api.hyperliquid.xyz/info"

BOTS = [
    {
        "label":       "Wallet 1",
        "wallet":      "0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94",
        "service":     "stochvol-bot-2",
        "log":         Path("/root/crypto-algo-bot/live/stochvol2.log"),
        "state_file":  Path("/root/crypto-algo-bot/live/positions_state_2.json"),
        "dedup_file":  Path("/root/crypto-algo-bot/live/last_entry_candle_2.json"),
    },
    {
        "label":       "Wallet 2",
        "wallet":      "0xb2A1B87B1B91Ad37520594263958cED3948151fF",
        "service":     "stochvol-bot",
        "log":         Path("/root/crypto-algo-bot/live/stochvol.log"),
        "state_file":  Path("/root/crypto-algo-bot/live/positions_state.json"),
        "dedup_file":  Path("/root/crypto-algo-bot/live/last_entry_candle.json"),
    },
]

# ── Helpers ───────────────────────────────────────────────────

def hl_post(payload):
    try:
        r = requests.post(HL_API, json=payload, timeout=5)
        return r.json()
    except Exception:
        return {}


def get_equity(wallet):
    data = hl_post({"type": "spotClearinghouseState", "user": wallet})
    for b in data.get("balances", []):
        if b.get("coin") == "USDC":
            return float(b["total"])
    return None


def get_positions(wallet):
    data = hl_post({"type": "clearinghouseState", "user": wallet})
    positions = []
    for ap in data.get("assetPositions", []):
        p = ap["position"]
        szi = float(p.get("szi", 0))
        if szi == 0:
            continue
        positions.append({
            "coin": p["coin"],
            "side": "long" if szi > 0 else "short",
            "size": abs(szi),
            "entry": float(p.get("entryPx", 0)),
            "upnl": float(p.get("unrealizedPnl", 0)),
        })
    return positions


def service_status(name):
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "unknown"


def file_age(path):
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - mtime


def fmt_age(td):
    if td is None:
        return "MISSING"
    secs = int(td.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h {(secs % 3600) // 60}m ago"


def last_loop_time(log_path):
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text().split("\n")
        for line in reversed(lines):
            if "Sleeping" in line:
                m = re.match(r"\[(.*?)\]", line)
                if m:
                    return m.group(1)
        return None
    except Exception:
        return None


def last_reconciliation(log_path):
    if not log_path.exists():
        return None, None
    try:
        lines = log_path.read_text().split("\n")
        recon_line = None
        recon_details = []
        for i, line in enumerate(lines):
            if "Reconcil" in line:
                recon_line = line.strip()
                recon_details = []
            elif recon_line and ("Restored" in line or "DEGRADED" in line or "No open" in line):
                recon_details.append(line.strip())
        return recon_line, recon_details
    except Exception:
        return None, None


def recent_trades(log_path, n=5):
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text().split("\n")
        trades = []
        for line in reversed(lines):
            if any(x in line for x in ["📤 ENTRY", "✅ Exit", "💰 PnL", "ENTRY filled", "EXIT filled"]):
                trades.append(line.strip())
            if len(trades) >= n:
                break
        return list(reversed(trades))
    except Exception:
        return []


def state_file_health(path):
    if not path.exists():
        return "MISSING", None
    try:
        data = json.loads(path.read_text())
        n_pos = len(data.get("positions", {}))
        return "OK", n_pos
    except Exception as e:
        return f"CORRUPT: {e}", None


# ── Main ──────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'=' * 64}")
    print(f"  StochVol V4 — Ops Check  |  {now}")
    print(f"{'=' * 64}")

    total_eq = 0.0
    total_upnl = 0.0
    all_ok = True

    for bot in BOTS:
        status = service_status(bot["service"])
        equity = get_equity(bot["wallet"])
        positions = get_positions(bot["wallet"])
        loop_time = last_loop_time(bot["log"])
        recon_line, recon_details = last_reconciliation(bot["log"])
        state_health, state_n = state_file_health(bot["state_file"])
        state_age = file_age(bot["state_file"])
        dedup_age = file_age(bot["dedup_file"])
        trades = recent_trades(bot["log"])

        ok = status == "active"
        if not ok:
            all_ok = False

        eq_str = f"${equity:.2f}" if equity else "N/A"
        if equity:
            total_eq += equity

        icon = "OK" if ok else "FAIL"
        print(f"\n  [{icon}] {bot['label']} — {bot['service']}")
        print(f"  {'─' * 58}")

        # Service + equity
        print(f"    Service       : {status}")
        print(f"    Equity        : {eq_str}")

        # Positions
        if positions:
            upnl_sum = sum(p["upnl"] for p in positions)
            total_upnl += upnl_sum
            coins = [f"{p['coin']} {p['side'][0].upper()} {p['upnl']:+.2f}" for p in positions]
            print(f"    Positions ({len(positions)}) : {', '.join(coins)}")
            print(f"    Unrealized    : ${upnl_sum:+.4f}")
        else:
            print(f"    Positions     : none")

        # State files
        state_flag = "OK" if state_health == "OK" else "!!"
        print(f"    State file    : [{state_flag}] {state_health} ({state_n} pos) — {fmt_age(state_age)}")
        print(f"    Dedup file    : {fmt_age(dedup_age)}")

        # Loop timing
        if loop_time:
            print(f"    Last loop     : {loop_time}")
        else:
            print(f"    Last loop     : unknown")
            all_ok = False

        # Stale loop check
        if state_age and state_age > timedelta(minutes=10):
            print(f"    !! State file stale (>{int(state_age.total_seconds() // 60)}m)")
            all_ok = False

        # Reconciliation
        if recon_line:
            ts_match = re.match(r"\[(.*?)\]", recon_line)
            ts = ts_match.group(1) if ts_match else ""
            msg = recon_line.split("] ", 1)[-1] if "] " in recon_line else recon_line
            print(f"    Last recon    : {msg} ({ts})")
            if recon_details:
                for d in recon_details[-4:]:
                    d_clean = d.split("] ", 1)[-1] if "] " in d else d
                    print(f"      {d_clean}")
        else:
            print(f"    Last recon    : none found in logs")

        # Recent trades
        if trades:
            print(f"    Recent trades :")
            for t in trades[-3:]:
                t_clean = t.split("] ", 1)[-1] if "] " in t else t
                print(f"      {t_clean}")

    # Summary
    print(f"\n{'─' * 64}")
    print(f"  Total equity    : ${total_eq:.2f}")
    print(f"  Total unrealized: ${total_upnl:+.4f}")
    verdict = "ALL SYSTEMS OK" if all_ok else "CHECK REQUIRED"
    icon = "==" if all_ok else "!!"
    print(f"  Status          : [{icon}] {verdict}")
    print(f"{'=' * 64}\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

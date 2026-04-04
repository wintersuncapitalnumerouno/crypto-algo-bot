import requests
import subprocess
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv("/root/crypto-algo-bot/.env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = "1855483522"
HL_API         = "https://api.hyperliquid.xyz/info"
STATE_FILE     = "/root/crypto-algo-bot/live/circuit_breaker_state.json"
MAX_DAILY_LOSS_PCT = 0.03  # 3%

BOTS = [
    {"name": "StochVol V3 (Wallet 1)", "wallet": "0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94", "service": "stochvol-bot-2"},
    {"name": "StochVol V3 (Wallet 2)", "wallet": "0xb2A1B87B1B91Ad37520594263958cED3948151fF", "service": "stochvol-bot"},
]


def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except:
        pass


def get_equity(wallet):
    try:
        r = requests.post(HL_API, json={"type": "spotClearinghouseState", "user": wallet}, timeout=5)
        for b in r.json().get("balances", []):
            if b["coin"] == "USDC":
                return float(b["total"])
    except:
        pass
    return None


def get_total_equity():
    total = 0.0
    for bot in BOTS:
        eq = get_equity(bot["wallet"])
        if eq:
            total += eq
    return total


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {}


def save_state(state):
    json.dump(state, open(STATE_FILE, "w"))


def halt_bots():
    for bot in BOTS:
        try:
            subprocess.run(["systemctl", "stop", bot["service"]], timeout=10)
        except:
            pass


def main():
    state  = load_state()
    now    = datetime.now(timezone.utc)
    today  = now.strftime("%Y-%m-%d")
    equity = get_total_equity()

    if equity is None or equity == 0:
        return

    # Reset baseline at midnight UTC
    if state.get("date") != today:
        state = {"date": today, "baseline": equity, "halted": False}
        save_state(state)
        return

    # Already halted today — do nothing
    if state.get("halted"):
        return

    baseline = state.get("baseline", equity)
    loss_pct = (baseline - equity) / baseline

    if loss_pct >= MAX_DAILY_LOSS_PCT:
        halt_bots()
        state["halted"] = True
        save_state(state)
        loss_usd = baseline - equity
        send_telegram(
            f"🔴 <b>CIRCUIT BREAKER TRIGGERED</b>\n\n"
            f"Portfolio dropped <b>{loss_pct*100:.1f}%</b> today\n"
            f"Baseline: ${baseline:.2f} → Now: ${equity:.2f} (−${loss_usd:.2f})\n\n"
            f"Both bots have been <b>halted</b>.\n"
            f"Restart manually when ready:\n"
            f"<code>systemctl start stochvol-bot stochvol-bot-2</code>"
        )
        print(f"CIRCUIT BREAKER: {loss_pct*100:.1f}% loss. Bots halted.")
    else:
        print(f"OK: {loss_pct*100:.2f}% loss today (limit: {MAX_DAILY_LOSS_PCT*100}%). Equity: ${equity:.2f}")


if __name__ == "__main__":
    main()

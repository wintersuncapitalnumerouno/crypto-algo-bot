import requests
import subprocess
from datetime import datetime, timezone, timedelta
import csv
import os

import os as _os; from dotenv import load_dotenv as _ld; _ld("/root/crypto-algo-bot/.env"); TELEGRAM_TOKEN = _os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = "1855483522"
HL_API = "https://api.hyperliquid.xyz/info"

BOTS = [
    {
        "name":       "StochVol V4 (Wallet 1)",
        "wallet":     "0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94",
        "service":    "stochvol-bot-2",
        "trades_csv": "/root/crypto-algo-bot/live/stochvol2_trades.csv",
        "csv_format": "stochvol",
        "inception":  71.34,
    },
    {
        "name":       "StochVol V4 (Wallet 2)",
        "wallet":     "0xb2A1B87B1B91Ad37520594263958cED3948151fF",
        "service":    "stochvol-bot",
        "trades_csv": "/root/crypto-algo-bot/live/stochvol_trades.csv",
        "csv_format": "stochvol",
        "inception":  51.34,
    },
]


def get_equity(wallet):
    try:
        r = requests.post(HL_API, json={"type": "spotClearinghouseState", "user": wallet}, timeout=5)
        for b in r.json().get("balances", []):
            if b["coin"] == "USDC":
                return float(b["total"])
    except:
        pass
    return None


def get_positions(wallet):
    try:
        r = requests.post(HL_API, json={"type": "clearinghouseState", "user": wallet}, timeout=5)
        return [p["position"]["coin"] for p in r.json().get("assetPositions", [])
                if float(p["position"]["szi"]) != 0]
    except:
        return []


def get_service_status(service):
    try:
        result = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "unknown"


def compute_pnl_ema16(csv_path):
    now  = datetime.now(timezone.utc)
    c24  = now - timedelta(hours=24)
    c7d  = now - timedelta(days=7)
    c14d = now - timedelta(days=14)
    c30d = now - timedelta(days=30)
    p24 = p7d = p14d = p30d = ptot = 0.0
    inc_eq = None
    trades = 0
    if not os.path.exists(csv_path):
        return None, None, None, None, None, None, None
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if row.get("action") != "close":
                continue
            try:
                pnl = float(row["pnl_usd"])
                ts  = datetime.strptime(row["timestamp"].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except:
                continue
            ptot   += pnl
            trades += 1
            if inc_eq is None:
                try:
                    inc_eq = float(row["equity_after"]) - pnl
                except:
                    pass
            if ts >= c24:  p24  += pnl
            if ts >= c7d:  p7d  += pnl
            if ts >= c14d: p14d += pnl
            if ts >= c30d: p30d += pnl
    return p24, p7d, p14d, p30d, ptot, inc_eq, trades


def compute_pnl_stochvol(csv_path):
    now  = datetime.now(timezone.utc)
    c24  = now - timedelta(hours=24)
    c7d  = now - timedelta(days=7)
    c14d = now - timedelta(days=14)
    c30d = now - timedelta(days=30)
    if not os.path.exists(csv_path):
        return None, None, None, None, None, None, None
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    if not rows:
        return None, None, None, None, None, None, None
    try:
        inc_eq = float(rows[0]["equity"])
    except:
        inc_eq = None
    entries = {}
    p24 = p7d = p14d = p30d = ptot = 0.0
    trades = 0
    for row in rows:
        coin = row["coin"]
        if row.get("type") == "entry":
            try:
                entries[coin] = {
                    "price":     float(row["price"]),
                    "size_usd":  float(row["size_usd"]),
                    "direction": row["direction"],
                }
            except:
                pass
        elif row.get("type") == "exit":
            entry = entries.get(coin)
            if not entry:
                continue
            try:
                ep  = float(row["price"])
                xp  = entry["price"]
                sz  = entry["size_usd"]
                pnl = (ep - xp) / xp * sz if entry["direction"] == "long" else (xp - ep) / xp * sz
                ts_str = row["timestamp"].strip()
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                ptot   += pnl
                trades += 1
                if ts >= c24:  p24  += pnl
                if ts >= c7d:  p7d  += pnl
                if ts >= c14d: p14d += pnl
                if ts >= c30d: p30d += pnl
                entries.pop(coin, None)
            except:
                pass
    return p24, p7d, p14d, p30d, ptot, inc_eq, trades


def fmt_pnl(val, inc=None):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    s = f"{sign}${val:.2f}"
    if inc and inc > 0:
        s += f" ({sign}{val / inc * 100:.1f}%)"
    return s


def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except:
        pass


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"🤖 <b>Heartbeat</b> — {now}", ""]

    total_eq   = 0.0
    total_inc  = 0.0
    total_p24  = 0.0
    total_p7d  = 0.0
    total_p14d = 0.0
    total_p30d = 0.0
    total_ptot = 0.0
    all_ok     = True

    for bot in BOTS:
        status    = get_service_status(bot["service"])
        equity    = get_equity(bot["wallet"])
        positions = get_positions(bot["wallet"])
        ok = status == "active"
        if not ok:
            all_ok = False
        if equity:
            total_eq += equity

        fmt = bot.get("csv_format", "ema16")
        if fmt == "ema16":
            p24, p7d, p14d, p30d, ptot, inc_eq, n = compute_pnl_ema16(bot["trades_csv"])
        else:
            p24, p7d, p14d, p30d, ptot, inc_eq, n = compute_pnl_stochvol(bot["trades_csv"])

        # use hardcoded inception if CSV didn't yield one
        if inc_eq is None:
            inc_eq = bot.get("inception")

        if p24  is not None: total_p24  += p24
        if p7d  is not None: total_p7d  += p7d
        if p14d is not None: total_p14d += p14d
        if p30d is not None: total_p30d += p30d
        if ptot is not None: total_ptot += ptot
        if inc_eq:           total_inc  += inc_eq

        icon    = "✅" if ok else "❌"
        eq_str  = f"${equity:.2f}" if equity else "N/A"
        pos_str = ", ".join(positions) if positions else "none"

        lines.append(f"{icon} <b>{bot['name']}</b>")
        lines.append(f"   Service  : {status}")
        lines.append(f"   Equity   : {eq_str}")
        lines.append("   Positions: " + pos_str)
        lines.append(f"   PnL 24h  : {fmt_pnl(p24,  inc_eq)}")
        lines.append(f"   PnL 7d   : {fmt_pnl(p7d,  inc_eq)}")
        lines.append(f"   PnL 14d  : {fmt_pnl(p14d, inc_eq)}")
        lines.append(f"   PnL 30d  : {fmt_pnl(p30d, inc_eq)}")
        lines.append(f"   PnL total: {fmt_pnl(ptot, inc_eq)}")
        if n:
            lines.append(f"   Trades   : {n} closed")
        lines.append("")

    # Portfolio summary
    pct_str = f" ({total_ptot / total_inc * 100:+.1f}%)" if total_inc > 0 else ""
    lines.append(f"💰 <b>Total equity : ${total_eq:.2f}</b>")
    lines.append(f"📈 PnL 24h    : {fmt_pnl(total_p24)}")
    lines.append(f"📈 PnL 7d     : {fmt_pnl(total_p7d)}")
    lines.append(f"📈 PnL 14d    : {fmt_pnl(total_p14d)}")
    lines.append(f"📈 PnL 30d    : {fmt_pnl(total_p30d)}")
    lines.append(f"📈 PnL total  : {fmt_pnl(total_ptot)}{pct_str}")
    lines.append("")
    lines.append("🟢 All systems OK" if all_ok else "🔴 CHECK REQUIRED")

    msg = "\n".join(lines)
    send_telegram(msg)
    print(msg)


if __name__ == "__main__":
    main()

import requests
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
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
        "bot_id":     "wallet1",
        "trades_csv": "/root/crypto-algo-bot/live/stochvol2_trades.csv",
        "hl_csv":     "/root/crypto-algo-bot/live/stochvol2_trades_hl.csv",
        "hl_cutoff":  "2026-04-09 08:02:34",
        "csv_format": "stochvol",
    },
    {
        "name":       "StochVol V4 (Wallet 2)",
        "wallet":     "0xb2A1B87B1B91Ad37520594263958cED3948151fF",
        "service":    "stochvol-bot",
        "bot_id":     "wallet2",
        "trades_csv": "/root/crypto-algo-bot/live/stochvol_trades.csv",
        "hl_csv":     "/root/crypto-algo-bot/live/stochvol_trades_hl.csv",
        "hl_cutoff":  "2026-04-09 08:02:31",
        "csv_format": "stochvol",
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


def compute_pnl_from_fills(wallet):
    """Fetch fills from Hyperliquid API and sum closedPnl by time window."""
    now    = datetime.now(timezone.utc)
    c24    = now - timedelta(hours=24)
    c7d    = now - timedelta(days=7)
    c14d   = now - timedelta(days=14)
    c30d   = now - timedelta(days=30)
    p24 = p7d = p14d = p30d = ptot = 0.0
    trades = 0

    # Paginate through all available fills (up to 10k via HL API)
    max_pages = 20
    start_ms = 0  # from the beginning
    try:
        for _ in range(max_pages):
            payload = {"type": "userFillsByTime", "user": wallet,
                       "startTime": start_ms, "aggregateByTime": True}
            r = requests.post(HL_API, json=payload, timeout=10)
            r.raise_for_status()
            fills = r.json()
            if not fills:
                break
            for fill in fills:
                pnl = float(fill["closedPnl"])
                if pnl == 0:
                    continue
                ts = datetime.fromtimestamp(fill["time"] / 1000, tz=timezone.utc)
                ptot   += pnl
                trades += 1
                if ts >= c24:  p24  += pnl
                if ts >= c7d:  p7d  += pnl
                if ts >= c14d: p14d += pnl
                if ts >= c30d: p30d += pnl
            if len(fills) < 2000:
                break
            # Next page: start after last fill's timestamp
            start_ms = fills[-1]["time"] + 1
    except Exception:
        return None, None, None, None, None, None, None

    if trades == 0:
        return None, None, None, None, None, None, None
    return p24, p7d, p14d, p30d, ptot, None, trades


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
    lines = [f"\U0001f916 <b>Heartbeat</b> \u2014 {now}", ""]

    total_eq   = 0.0
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
            p24, p7d, p14d, p30d, ptot, inc_eq, n = compute_pnl_from_fills(bot["wallet"])

        if p24  is not None: total_p24  += p24
        if p7d  is not None: total_p7d  += p7d
        if p14d is not None: total_p14d += p14d
        if p30d is not None: total_p30d += p30d
        if ptot is not None: total_ptot += ptot

        icon    = "\u2705" if ok else "\u274c"
        eq_str  = f"${equity:.2f}" if equity else "N/A"
        pos_str = ", ".join(positions) if positions else "none"

        lines.append(f"{icon} <b>{bot['name']}</b>")
        lines.append(f"   Service  : {status}")
        lines.append(f"   Equity   : {eq_str}")
        lines.append("   Positions: " + pos_str)
        lines.append(f"   PnL 24h  : {fmt_pnl(p24,  equity)}")
        lines.append(f"   PnL 7d   : {fmt_pnl(p7d,  equity)}")
        lines.append(f"   PnL 14d  : {fmt_pnl(p14d, equity)}")
        lines.append(f"   PnL 30d  : {fmt_pnl(p30d, equity)}")
        lines.append(f"   PnL total: {fmt_pnl(ptot, equity)}")
        if n:
            lines.append(f"   Trades   : {n} closed")
        lines.append("")

    # Portfolio summary
    pct_str = f" ({total_ptot / total_eq * 100:+.1f}%)" if total_eq > 0 else ""
    lines.append(f"\U0001f4b0 <b>Total equity : ${total_eq:.2f}</b>")
    lines.append(f"\U0001f4c8 PnL 24h    : {fmt_pnl(total_p24)}")
    lines.append(f"\U0001f4c8 PnL 7d     : {fmt_pnl(total_p7d)}")
    lines.append(f"\U0001f4c8 PnL 14d    : {fmt_pnl(total_p14d)}")
    lines.append(f"\U0001f4c8 PnL 30d    : {fmt_pnl(total_p30d)}")
    lines.append(f"\U0001f4c8 PnL total  : {fmt_pnl(total_ptot)}{pct_str}")
    lines.append("")
    lines.append("\U0001f7e2 All systems OK" if all_ok else "\U0001f534 CHECK REQUIRED")

    msg = "\n".join(lines)
    send_telegram(msg)
    print(msg)


if __name__ == "__main__":
    main()

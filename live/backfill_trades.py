#!/usr/bin/env python3
"""
backfill_trades.py — Reconstruct trade history from Hyperliquid fills.

Fetches all fills via userFillsByTime API, pairs Open/Close fills into
complete trades, and writes trades_master-compatible CSV.

Writes: live/trades_master_backfill.csv  (review before merging)
Does NOT touch trades_master.csv directly.

Run once, on demand. Requires network access to HL API.
"""
import requests
import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path

HL_API = "https://api.hyperliquid.xyz/info"
MAX_PAGES = 20
OUTPUT = Path(__file__).resolve().parent / "trades_master_backfill.csv"

WALLETS = [
    {"wallet": "0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94", "bot_id": "wallet1"},
    {"wallet": "0xb2A1B87B1B91Ad37520594263958cED3948151fF", "bot_id": "wallet2"},
]

FIELDS = [
    "trade_id", "strategy", "bot_id", "coin", "direction", "timeframe",
    "entry_time", "exit_time", "entry_price", "exit_price", "size_usd",
    "stop_loss", "take_profit", "vol_ratio", "leverage", "exit_reason",
    "pnl_usd", "pnl_pct", "fee_usd", "duration_min", "equity_after",
]


def fetch_all_fills(wallet):
    """Paginate through all fills for a wallet."""
    all_fills = []
    start_ms = 0
    for _ in range(MAX_PAGES):
        r = requests.post(HL_API, json={
            "type": "userFillsByTime", "user": wallet,
            "startTime": start_ms, "aggregateByTime": True,
        }, timeout=15)
        r.raise_for_status()
        fills = r.json()
        if not fills:
            break
        all_fills.extend(fills)
        if len(fills) < 2000:
            break
        start_ms = fills[-1]["time"] + 1
    return all_fills


def reconstruct_trades(fills, bot_id):
    """Pair open/close fills into trade records."""
    trades = []
    # Track open positions: coin -> {direction, entry_price, size_coin, size_usd, entry_time, fee}
    positions = {}

    for fill in sorted(fills, key=lambda f: f["time"]):
        coin = fill["coin"]
        d = fill.get("dir", "")
        px = float(fill["px"])
        sz = float(fill["sz"])  # size in coins
        fee = float(fill.get("fee", "0"))
        ts = datetime.fromtimestamp(fill["time"] / 1000, tz=timezone.utc)

        if d.startswith("Open"):
            direction = "long" if "Long" in d else "short"
            size_usd = px * sz
            if coin in positions:
                # Add to existing position (averaging in)
                pos = positions[coin]
                old_usd = pos["size_usd"]
                new_usd = old_usd + size_usd
                pos["entry_price"] = (pos["entry_price"] * old_usd + px * size_usd) / new_usd
                pos["size_coin"] += sz
                pos["size_usd"] = new_usd
                pos["fee"] += fee
            else:
                positions[coin] = {
                    "direction": direction,
                    "entry_price": px,
                    "size_coin": sz,
                    "size_usd": size_usd,
                    "entry_time": ts,
                    "fee": fee,
                }

        elif d.startswith("Close"):
            closed_pnl = float(fill["closedPnl"])
            pos = positions.get(coin)
            if not pos:
                continue

            total_fee = pos["fee"] + fee

            # Determine if this is a full or partial close
            remaining = pos["size_coin"] - sz
            if remaining <= 1e-9:
                # Full close — emit trade
                duration = (ts - pos["entry_time"]).total_seconds() / 60
                pnl_pct = (closed_pnl / pos["size_usd"] * 100) if pos["size_usd"] > 0 else 0

                trades.append({
                    "trade_id": str(uuid.uuid4())[:8],
                    "strategy": "STOCHVOL_V4",
                    "bot_id": bot_id,
                    "coin": coin,
                    "direction": pos["direction"],
                    "timeframe": "5m",
                    "entry_time": pos["entry_time"].isoformat(),
                    "exit_time": ts.isoformat(),
                    "entry_price": f"{pos['entry_price']:.6f}",
                    "exit_price": f"{px:.6f}",
                    "size_usd": f"{pos['size_usd']:.2f}",
                    "stop_loss": "",
                    "take_profit": "",
                    "vol_ratio": "",
                    "leverage": "5",
                    "exit_reason": "unknown",
                    "pnl_usd": f"{closed_pnl:.4f}",
                    "pnl_pct": f"{pnl_pct:.4f}",
                    "fee_usd": f"{total_fee:.4f}",
                    "duration_min": f"{duration:.1f}",
                    "equity_after": "",
                })
                positions.pop(coin)
            else:
                # Partial close — emit a trade for the closed portion
                partial_usd = (sz / pos["size_coin"]) * pos["size_usd"]
                duration = (ts - pos["entry_time"]).total_seconds() / 60
                pnl_pct = (closed_pnl / partial_usd * 100) if partial_usd > 0 else 0

                trades.append({
                    "trade_id": str(uuid.uuid4())[:8],
                    "strategy": "STOCHVOL_V4",
                    "bot_id": bot_id,
                    "coin": coin,
                    "direction": pos["direction"],
                    "timeframe": "5m",
                    "entry_time": pos["entry_time"].isoformat(),
                    "exit_time": ts.isoformat(),
                    "entry_price": f"{pos['entry_price']:.6f}",
                    "exit_price": f"{px:.6f}",
                    "size_usd": f"{partial_usd:.2f}",
                    "stop_loss": "",
                    "take_profit": "",
                    "vol_ratio": "",
                    "leverage": "5",
                    "exit_reason": "unknown",
                    "pnl_usd": f"{closed_pnl:.4f}",
                    "pnl_pct": f"{pnl_pct:.4f}",
                    "fee_usd": f"{fee:.4f}",
                    "duration_min": f"{duration:.1f}",
                    "equity_after": "",
                })
                pos["size_coin"] = remaining
                pos["size_usd"] -= partial_usd
                pos["fee"] = 0  # fee already accounted for

    return trades


def main():
    all_trades = []
    for w in WALLETS:
        print(f"Fetching fills for {w['bot_id']} ({w['wallet'][:10]}...)...")
        fills = fetch_all_fills(w["wallet"])
        print(f"  Got {len(fills)} fills")
        trades = reconstruct_trades(fills, w["bot_id"])
        print(f"  Reconstructed {len(trades)} trades")
        all_trades.extend(trades)

    # Sort by exit_time
    all_trades.sort(key=lambda t: t["exit_time"])

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_trades)

    total_pnl = sum(float(t["pnl_usd"]) for t in all_trades)
    print(f"\nWrote {len(all_trades)} trades -> {OUTPUT}")
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"\nReview the file, then merge into trades_master.csv if it looks correct.")


if __name__ == "__main__":
    main()

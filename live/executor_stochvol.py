# =============================================================
# live/executor_stochvol.py — StochVol V3 Live Executor — Wallet 2
# =============================================================
#
# Runs StochVol V3 strategy live on Hyperliquid.
# Wallet 2 (original StochVol wallet).
#
# HOW TO RUN:
#   managed by systemd stochvol-bot.service
#
# HOW TO STOP:
#   systemctl stop stochvol-bot
#
# MONITOR:
#   tail -f live/stochvol.log
# =============================================================

import os
import sys
import time
import csv
import json
import math
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

# ── Telegram notifications ────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1855483522")

def send_telegram(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        log(f"  Telegram error: {e}")

import requests
from hyperliquid.exchange import Exchange
from live.basket_optimizer import build_entry_basket, log_basket
from eth_account import Account

# ── Config ────────────────────────────────────────────────────
PRIVATE_KEY    = os.getenv("HL_WALLET2_PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("HL_WALLET2_WALLET_ADDRESS")
EXPECTED_WALLET = "0xb2A1B87B1B91Ad37520594263958cED3948151fF"
DEDUP_FILE = "last_entry_candle.json"
HL_API = "https://api.hyperliquid.xyz"

COINS = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP", "MERL", "HEMI"]

LOOP_INTERVAL = 300          # 5 minutes
RISK_PCT = 0.005             # 0.5% equity per trade
STOP_PCT = 0.02              # 2% fixed stop
LEVERAGE = 5
MIN_NOTIONAL = 11.0          # minimum order size USD
BASKET_SHADOW = True
SLIPPAGE = 0.01              # 1% slippage buffer for IOC

# Volume sizing (StochVol specific)
VOL_SIZE_MIN = 1.0
VOL_SIZE_MAX = 2.0

# Trail stop params
TRAIL_TRIGGER = 0.005        # activate at +0.5%
TRAIL_OFFSET = 0.003         # 0.3% trailing distance
TRAIL_TIGHT_TRIGGER = 0.03   # tighten at +3%
TRAIL_TIGHT_OFFSET = 0.002   # 0.2% tight distance

# Coin → Hyperliquid symbol mapping
COIN_MAP = {
    "PEPE": "kPEPE",
    "SOL": "SOL",
    "AAVE": "AAVE",
    "DOGE": "DOGE",
    "LINK": "LINK",
    "ETH": "ETH",
    "XRP": "XRP",
    "MERL": "MERL",
    "HEMI": "HEMI",
}

# Size decimals per coin
SZ_DECIMALS = {
    "kPEPE": 0,
    "SOL": 2,
    "AAVE": 2,
    "DOGE": 0,
    "LINK": 1,
    "ETH": 4,
    "XRP": 0,
    "MERL": 0,
    "HEMI": 0,
}

TRADES_CSV = Path("live/stochvol_trades.csv")


# ── Logging ───────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = f"[{ts}] {msg}"
    print(out, flush=True)


# ── Price rounding ────────────────────────────────────────────

def round_sig(x: float, sig: int = 5) -> float:
    if x == 0:
        return 0.0
    d = math.ceil(math.log10(abs(x)))
    power = sig - d
    factor = 10 ** power
    return round(x * factor) / factor


def round_size(size: float, coin_hl: str) -> float:
    decimals = SZ_DECIMALS.get(coin_hl, 2)
    factor = 10 ** decimals
    return math.floor(size * factor) / factor


# ── Hyperliquid API ───────────────────────────────────────────

def hl_post(endpoint: str, payload: dict) -> dict:
    r = requests.post(f"{HL_API}{endpoint}", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def get_equity() -> float:
    payload = {"type": "spotClearinghouseState", "user": WALLET_ADDRESS}
    data = hl_post("/info", payload)
    log(f"DEBUG get_equity wallet={WALLET_ADDRESS} data={data}")

    for asset in data.get("balances", []):
        if asset.get("coin") == "USDC":
            try:
                return float(asset.get("total", 0))
            except Exception:
                pass

    return 0.0


def get_positions() -> dict:
    payload = {"type": "clearinghouseState", "user": WALLET_ADDRESS}
    data = hl_post("/info", payload)
    positions = {}

    for pos in data.get("assetPositions", []):
        p = pos.get("position", {})
        coin = p.get("coin", "")
        size = float(p.get("szi", 0))

        if size != 0:
            positions[coin] = {
                "size": size,
                "entry_price": float(p.get("entryPx", 0)),
                "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                "direction": "long" if size > 0 else "short",
            }

    return positions


def get_mid_price(coin_hl: str) -> float:
    payload = {"type": "l2Book", "coin": coin_hl}
    data = hl_post("/info", payload)
    levels = data.get("levels", [[], []])
    bids = levels[0]
    asks = levels[1]

    if bids and asks:
        return (float(bids[0]["px"]) + float(asks[0]["px"])) / 2

    return 0.0


def get_exchange():
    account  = Account.from_key(PRIVATE_KEY)
    exchange = Exchange(account, HL_API)
    return exchange


def place_order(exchange, coin_hl: str, is_buy: bool, size: float,
                price: float, reduce_only: bool = False) -> dict:
    """Place IOC limit order with slippage buffer."""
    if is_buy:
        limit_px = round_sig(price * (1 + SLIPPAGE))
    else:
        limit_px = round_sig(price * (1 - SLIPPAGE))

    sz = round_size(size, coin_hl)
    result = exchange.order(
        coin_hl, is_buy, sz, limit_px,
        {"limit": {"tif": "Ioc"}},
        reduce_only=reduce_only,
    )
    if isinstance(result, dict) and result.get("status") == "err":
        raise RuntimeError(f"Order rejected: {result.get('response')}")
    statuses = result.get("response", {}).get("data", {}).get("statuses", [])
    if statuses and "error" in statuses[0]:
        raise RuntimeError(f"Order fill error: {statuses[0]['error']}")
    return result


def set_leverage(exchange, coin_hl: str, leverage: int):
    try:
        exchange.update_leverage(leverage, coin_hl, is_cross=False)
    except Exception as e:
        log(f"  ⚠️  Leverage error {coin_hl}: {e}")


# ── Trade logging ─────────────────────────────────────────────

def log_trade(record: dict):
    TRADES_CSV.parent.mkdir(exist_ok=True)
    write_header = not TRADES_CSV.exists()

    with open(TRADES_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(record.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(record)


# ── Position state ────────────────────────────────────────────

class Position:
    def __init__(self, coin, direction, entry_price, size_usd, stop_loss, entry_candle, vol_ratio):
        self.coin = coin
        self.direction = direction
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.stop_loss = stop_loss
        self.initial_sl = stop_loss
        self.entry_candle = entry_candle
        self.vol_ratio = vol_ratio
        self.trail_active = False
        self.best_price = entry_price
        self.entry_time = datetime.now(timezone.utc)

    def update_trail(self, current_price: float):
        """Update trailing stop. Returns new stop level."""
        if self.direction == "long":
            if current_price > self.best_price:
                self.best_price = current_price
            profit_pct = (self.best_price - self.entry_price) / self.entry_price
        else:
            if current_price < self.best_price:
                self.best_price = current_price
            profit_pct = (self.entry_price - self.best_price) / self.entry_price

        if profit_pct >= TRAIL_TRIGGER:
            self.trail_active = True

        if self.trail_active:
            offset = TRAIL_TIGHT_OFFSET if profit_pct >= TRAIL_TIGHT_TRIGGER else TRAIL_OFFSET
            if self.direction == "long":
                new_sl = self.best_price * (1 - offset)
                if new_sl > self.stop_loss:
                    self.stop_loss = new_sl
            else:
                new_sl = self.best_price * (1 + offset)
                if new_sl < self.stop_loss:
                    self.stop_loss = new_sl

        return self.stop_loss


# ── Main executor ─────────────────────────────────────────────

class StochVolExecutor:

    def __init__(self):
        from live.data_feed import DataFeed
        from live.signal_engine_stochvol import StochVolSignalEngine

        self.feed = DataFeed()
        self.engine = StochVolSignalEngine()
        self.exchange = get_exchange()
        self.positions = {}
        self.last_entry_candle = {}
        self._load_entry_candle_state()
        self.last_exit_candle = {}
        self.equity = 0.0

        log("=" * 60)
        log("  StochVol V3 Executor starting — Wallet 2")
        log(f"  Wallet : {WALLET_ADDRESS}")
        log(f"  Coins  : {', '.join(COINS)}")
        log(f"  Risk   : {RISK_PCT * 100}% per trade | {LEVERAGE}x leverage")
        log("=" * 60)

        self._validate_env()
        self._set_leverage_all()
        self._sync_positions_on_startup()

    def _validate_env(self):
        if not PRIVATE_KEY or not WALLET_ADDRESS:
            log(f"❌ STARTUP INVARIANT FAILED: wallet env vars not set in .env")
            send_telegram(f"🚨 <b>Bot refused to start</b>\nReason: wallet env vars missing from .env")
            sys.exit(1)

        if len(PRIVATE_KEY) != 66:
            log(f"❌ STARTUP INVARIANT FAILED: private key length {len(PRIVATE_KEY)} — expected 66")
            send_telegram(f"🚨 <b>Bot refused to start</b>\nReason: private key wrong length ({len(PRIVATE_KEY)})")
            sys.exit(1)

        if not WALLET_ADDRESS.startswith("0x") or len(WALLET_ADDRESS) != 42:
            log(f"❌ STARTUP INVARIANT FAILED: wallet address format invalid: {WALLET_ADDRESS}")
            send_telegram(f"🚨 <b>Bot refused to start</b>\nReason: wallet address format invalid")
            sys.exit(1)

        if WALLET_ADDRESS.lower() != EXPECTED_WALLET.lower():
            log(f"❌ STARTUP INVARIANT FAILED: wallet mismatch")
            log(f"   Expected: {EXPECTED_WALLET}")
            log(f"   Got:      {WALLET_ADDRESS}")
            send_telegram(f"🚨 <b>Bot refused to start — WALLET MISMATCH</b>\nExpected: {EXPECTED_WALLET[:10]}...\nGot: {WALLET_ADDRESS[:10]}...")
            sys.exit(1)

        state_path = Path(__file__).parent / DEDUP_FILE
        if state_path.exists():
            try:
                import json
                json.loads(state_path.read_text())
            except Exception as e:
                log(f"❌ STARTUP INVARIANT FAILED: dedup state file corrupted: {e}")
                send_telegram(f"🚨 <b>Bot refused to start</b>\nReason: dedup state file corrupted\n{e}")
                sys.exit(1)

        log("✅ Credentials validated")
        log(f"✅ Wallet address verified: {WALLET_ADDRESS}")

    def _set_leverage_all(self):
        for coin in COINS:
            coin_hl = COIN_MAP[coin]
            try:
                set_leverage(self.exchange, coin_hl, LEVERAGE)
                log(f"  ✅ Leverage {LEVERAGE}x set for {coin_hl}")
                time.sleep(0.3)
            except Exception as e:
                log(f"  ⚠️  Leverage error {coin}: {e}")

    def _sync_positions_on_startup(self):
        """Restore open positions on restart so we don't orphan trades."""
        log("🔄 Syncing positions on startup...")
        try:
            live_pos = get_positions()
            for coin in COINS:
                coin_hl = COIN_MAP[coin]
                if coin_hl in live_pos:
                    p = live_pos[coin_hl]
                    ep = p["entry_price"]
                    direction = p["direction"]
                    sl = ep * (1 - STOP_PCT) if direction == "long" else ep * (1 + STOP_PCT)
                    size_usd = abs(p["size"]) * ep

                    pos = Position(
                        coin=coin,
                        direction=direction,
                        entry_price=ep,
                        size_usd=size_usd,
                        stop_loss=sl,
                        entry_candle="restored",
                        vol_ratio=1.0,
                    )
                    self.positions[coin] = pos
                    log(f"  🔁 Restored {direction} {coin} @ {ep:.4f} sl={sl:.4f}")
        except Exception as e:
            log(f"  ⚠️  Position sync error: {e}")

    def _get_equity(self) -> float:
        try:
            eq = get_equity()
            if eq > 0:
                self.equity = eq
            return self.equity
        except Exception as e:
            log(f"  ⚠️  Equity fetch error: {e}")
            return self.equity

    def _load_entry_candle_state(self):
        import json
        state_path = Path(__file__).parent / "last_entry_candle.json"
        try:
            if state_path.exists():
                self.last_entry_candle = json.loads(state_path.read_text())
                log(f"  Loaded entry candle state: {self.last_entry_candle}")
        except Exception as e:
            log(f"  Could not load entry candle state: {e}")

    def _save_entry_candle_state(self):
        import json
        state_path = Path(__file__).parent / "last_entry_candle.json"
        try:
            serializable = {k: str(v) for k, v in self.last_entry_candle.items()}
            state_path.write_text(json.dumps(serializable))
        except Exception as e:
            log(f"  Could not save entry candle state: {e}")

    def _calc_position_size(self, equity: float, stop_pct: float, vol_ratio: float) -> float:
        dollar_risk = equity * RISK_PCT
        vol_mult = min(max(vol_ratio, VOL_SIZE_MIN), VOL_SIZE_MAX)
        return (dollar_risk / stop_pct) * vol_mult

    def _enter_trade(self, coin: str, signal: dict, equity: float):
        coin_hl = COIN_MAP[coin]
        direction = signal["action"]
        price = get_mid_price(coin_hl)

        if price <= 0:
            log(f"  ⚠️  {coin}: could not get price")
            return

        vol_ratio = signal.get("vol_ratio", 1.0)
        sl = price * (1 - STOP_PCT) if direction == "long" else price * (1 + STOP_PCT)
        stop_pct = STOP_PCT

        size_usd = self._calc_position_size(equity, stop_pct, vol_ratio)
        size_coin = size_usd / price

        notional = size_coin * price
        if notional < MIN_NOTIONAL:
            log(f"  ⚠️  {coin}: notional ${notional:.2f} below min ${MIN_NOTIONAL}")
            return

        is_buy = direction == "long"

        log(
            f"  📤 {direction.upper()} {coin} | "
            f"price={price:.4f} size=${size_usd:.2f} sl={sl:.4f} vol_ratio={vol_ratio:.2f}"
        )

        try:
            resp = place_order(self.exchange, coin_hl, is_buy, size_coin, price)
            log(f"  ✅ Order placed: {resp}")
            direction_emoji = "🟢" if direction == "long" else "🔴"
            send_telegram(f"<b>StochVol WALLET 2 ENTRY — {coin} {direction_emoji} {direction.upper()}</b>\nPrice: {price:.6f} | Size: ${size_usd:.2f}\nStop: {sl:.6f} | Equity: ${equity:.2f}")

            if True:
                pos = Position(
                    coin=coin,
                    direction=direction,
                    entry_price=price,
                    size_usd=size_usd,
                    stop_loss=sl,
                    entry_candle=signal["candle_time"],
                    vol_ratio=vol_ratio,
                )
                self.positions[coin] = pos
                self.last_entry_candle[coin] = str(signal["candle_time"])
                self._save_entry_candle_state()

                log_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "coin": coin,
                    "type": "entry",
                    "direction": direction,
                    "price": round(price, 6),
                    "size_usd": round(size_usd, 2),
                    "stop_loss": round(sl, 6),
                    "vol_ratio": round(vol_ratio, 4),
                    "stoch_k": signal.get("stoch_k", 0),
                    "stoch_d": signal.get("stoch_d", 0),
                    "equity": round(equity, 2),
                    "candle_time": signal["candle_time"],
                })
        except Exception as e:
            log(f"  ❌ Order error {coin}: {e}")
            traceback.print_exc()

    def _exit_trade(self, coin: str, reason: str, current_price: float, candle_time: str):
        pos = self.positions.get(coin)
        if not pos:
            return

        coin_hl = COIN_MAP[coin]
        is_buy = pos.direction == "short"
        size_coin = pos.size_usd / pos.entry_price

        log(
            f"  📤 EXIT {coin} | reason={reason} "
            f"price={current_price:.4f} entry={pos.entry_price:.4f}"
        )

        try:
            resp = place_order(self.exchange, coin_hl, is_buy, size_coin, current_price, reduce_only=True)
            log(f"  ✅ Exit placed: {resp}")

            try:
                fill_px = float(resp["response"]["data"]["statuses"][0].get("filled", {}).get("avgPx"))
            except Exception:
                fill_px = None
            exit_price_for_log = fill_px if fill_px else current_price
            exit_price_source = "fill" if fill_px else "mark_fallback"
            log(f"  Exit price source: {exit_price_source} ({exit_price_for_log:.6f})")

            if True:
                if pos.direction == "long":
                    pnl_pct = (exit_price_for_log - pos.entry_price) / pos.entry_price
                else:
                    pnl_pct = (pos.entry_price - exit_price_for_log) / pos.entry_price

                pnl_usd = pos.size_usd * pnl_pct
                log(f"  💰 PnL: {pnl_pct * 100:+.2f}% (${pnl_usd:+.2f})")
                pnl_emoji = "✅" if pnl_pct >= 0 else "❌"
                send_telegram(f"<b>StochVol WALLET 2 EXIT — {coin} {pos.direction.upper()}</b>\nReason: {reason}\nPnL: {pnl_emoji} ${pnl_usd:+.2f} ({pnl_pct*100:+.2f}%)\nEquity: ${self.equity:.2f}")

                log_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "coin": coin,
                    "type": "exit",
                    "direction": pos.direction,
                    "price": round(exit_price_for_log, 6),
                    "price_source": exit_price_source,
                    "size_usd": round(pos.size_usd, 2),
                    "stop_loss": round(pos.stop_loss, 6),
                    "vol_ratio": round(pos.vol_ratio, 4),
                    "pnl_pct": round(pnl_pct * 100, 4),
                    "pnl_usd": round(pnl_usd, 4),
                    "exit_reason": reason,
                    "equity": round(self.equity, 2),
                    "candle_time": candle_time,
                })

                del self.positions[coin]
                self.last_exit_candle[coin] = candle_time

        except Exception as e:
            log(f"  ❌ Exit error {coin}: {e}")
            traceback.print_exc()

    def run_once(self):
        equity = self._get_equity()
        log(f"\n{'=' * 55}")
        log(f"  💰 Equity: ${equity:.2f} | Positions: {list(self.positions.keys())}")
        log(f"{'=' * 55}")

        shadow_candidates = []

        for coin in COINS:
            try:
                df_5m = self.feed.get_candles(coin)
                signal = self.engine.get_signal(coin, df_5m)
                candle_time = signal.get("candle_time", "")

                log(
                    f"  {coin:<5} action={signal['action']} "
                    f"vol_ratio={signal.get('vol_ratio', 0):.2f} "
                    f"K={signal.get('stoch_k', 0):.1f} "
                    f"D={signal.get('stoch_d', 0):.1f} "
                    f"candle={candle_time[:16]}"
                )

                current_price = get_mid_price(COIN_MAP[coin])

                # ── Manage open position ──────────────────────
                if coin in self.positions:
                    pos = self.positions[coin]
                    pos.update_trail(current_price)

                    stop_hit = (
                        (pos.direction == "long" and current_price <= pos.stop_loss) or
                        (pos.direction == "short" and current_price >= pos.stop_loss)
                    )

                    signal_exit = (
                        (pos.direction == "long" and signal.get("exit_long")) or
                        (pos.direction == "short" and signal.get("exit_short"))
                    )

                    if stop_hit:
                        reason = "trail_stop" if pos.trail_active else "stop_loss"
                        self._exit_trade(coin, reason, pos.stop_loss, candle_time)
                    elif signal_exit:
                        self._exit_trade(coin, "signal_exit", current_price, candle_time)

                # ── Check for new entry ───────────────────────
                if coin not in self.positions:
                    action = signal.get("action")

                    if action in ("long", "short"):
                        _s = dict(signal)
                        _s["coin"] = coin
                        shadow_candidates.append(_s)

                    if self.last_entry_candle.get(coin) == str(candle_time):
                        continue

                    if self.last_exit_candle.get(coin) == candle_time:
                        continue

                    if action in ("long", "short"):
                        if equity < MIN_NOTIONAL * 2:
                            log(f"  ⚠️  {coin}: equity too low (${equity:.2f})")
                            continue
                        self._enter_trade(coin, signal, equity)

                time.sleep(0.3)

            except Exception as e:
                log(f"  ❌ Error on {coin}: {e}")
                send_telegram(f"⚠️ StochVol WALLET 2 ERROR — {coin}\n{str(e)}")
                traceback.print_exc()

    def run(self):
        log("🚀 StochVol V3 (wallet 2) executor running. Ctrl+C or pkill to stop.")
        send_telegram("🤖 <b>StochVol V3 — WALLET 2 started</b>\nServer: Legatus | Coins: " + ", ".join(COINS))
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                log("⛔ Stopped by user.")
                break
            except Exception as e:
                log(f"❌ Loop error: {e}")
                traceback.print_exc()

            log(f"  ⏳ Sleeping {LOOP_INTERVAL}s...")
            time.sleep(LOOP_INTERVAL)

        if BASKET_SHADOW:
            try:
                shadow_allocs = build_entry_basket(shadow_candidates, equity, self.positions)
                if shadow_allocs:
                    log(f"  [SHADOW] Basket would select {len(shadow_allocs)} candidates")
                    for a in shadow_allocs:
                        log(
                            f"    [SHADOW] {a['coin']:<6} "
                            f"score={a['score']:.3f} "
                            f"size=${a['size_usd']:.2f} "
                            f"risk=${a['risk_usd']:.4f} "
                            f"stop={a['stop_pct']*100:.2f}%"
                        )
                else:
                    log("  [SHADOW] Basket: no candidates passed constraints")
            except Exception as e:
                log(f"  [SHADOW] Basket optimizer error: {e}")

if __name__ == "__main__":
    executor = StochVolExecutor()
    executor.run()

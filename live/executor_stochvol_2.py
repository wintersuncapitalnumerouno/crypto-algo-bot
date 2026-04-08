# =============================================================
# live/executor_stochvol_2.py — StochVol V4 Live Executor — Wallet 1
# =============================================================
#
# Runs StochVol V4 strategy live on Hyperliquid.
# Wallet 1 (formerly EMA16 wallet).
#
# HOW TO RUN:
#   managed by systemd stochvol-bot-2.service
#
# HOW TO STOP:
#   systemctl stop stochvol-bot-2
#
# MONITOR:
#   tail -f live/stochvol2.log
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
from live.basket_optimizer import build_entry_basket
from eth_account import Account

# ── Config ────────────────────────────────────────────────────
PRIVATE_KEY    = os.getenv("HL_WALLET1_PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("HL_WALLET1_WALLET_ADDRESS")
EXPECTED_WALLET = "0x9b808Eaa6A795f22C3154c2a8a22C9a1F916BD94"
DEDUP_FILE = "last_entry_candle_2.json"
POSITIONS_STATE_FILE = "positions_state_2.json"
HL_API = "https://api.hyperliquid.xyz"

COINS = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP", "MERL", "HEMI"]

LOOP_INTERVAL = 300          # 5 minutes
RISK_PCT = 0.005             # 0.5% equity per trade
STOP_PCT = 0.02              # 2% fixed stop
LEVERAGE = 5
COIN_LEVERAGE = {"MERL": 3, "HEMI": 3}
COIN_PRICE_DECIMALS = {"kPEPE": 6, "MERL": 6, "HEMI": 6}
MIN_NOTIONAL = 11.0          # minimum order size USD
BASKET_SHADOW = True
MAX_EXIT_RETRIES = 3         # halt trading after this many consecutive exit failures
SLIPPAGE = 0.01              # 1% slippage buffer for IOC

# Volume sizing (StochVol specific)
VOL_SIZE_MIN = 1.0
VOL_SIZE_MAX = 2.0

# Trail stop params
TRAIL_TRIGGER = 0.005        # activate at +0.5%
TRAIL_OFFSET = 0.003         # 0.3% trailing distance
TRAIL_TIGHT_TRIGGER = 0.03   # tighten at +3%
TRAIL_TIGHT_OFFSET = 0.002   # 0.2% tight distance

# Reconciliation tolerances
ENTRY_PRICE_TOLERANCE = 0.02  # 2% drift between saved and exchange entry price
SIZE_TOLERANCE = 0.02         # 2% drift between saved and exchange position size

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

TRADES_CSV = Path("live/stochvol2_trades.csv")


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
    # Uses spot clearinghouse — this wallet holds USDC on spot side
    payload = {"type": "spotClearinghouseState", "user": WALLET_ADDRESS}
    data = hl_post("/info", payload)

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
    max_dec = COIN_PRICE_DECIMALS.get(coin_hl, None)
    if is_buy:
        limit_px = round_sig(price * (1 + SLIPPAGE))
        if max_dec: limit_px = round(limit_px, max_dec)
    else:
        limit_px = round_sig(price * (1 - SLIPPAGE))
        if max_dec: limit_px = round(limit_px, max_dec)

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
    def __init__(self, coin, direction, entry_price, size_usd, size_coin,
                 stop_loss, entry_candle, vol_ratio):
        self.coin = coin
        self.direction = direction
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.size_coin = size_coin
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
        self.exit_fail_count = {}
        self.trading_halted = False
        self.halt_reason = ""
        self.halted_at = ""
        self.last_exit_error = {}
        self.halt_alert_sent = False

        log("=" * 60)
        log("  StochVol V4 Executor starting — Wallet 1")
        log(f"  Wallet : {WALLET_ADDRESS}")
        log(f"  Coins  : {', '.join(COINS)}")
        log(f"  Risk   : {RISK_PCT * 100}% per trade | {LEVERAGE}x default leverage")
        log("=" * 60)

        self._validate_env()
        self._set_leverage_all()
        self._sync_positions_on_startup()

    def _validate_env(self):
        if not PRIVATE_KEY or not WALLET_ADDRESS:
            log("❌ STARTUP INVARIANT FAILED: wallet env vars not set in .env")
            send_telegram("🚨 <b>Bot refused to start</b>\nReason: wallet env vars missing from .env")
            sys.exit(1)

        if len(PRIVATE_KEY) != 66:
            log(f"❌ STARTUP INVARIANT FAILED: private key length {len(PRIVATE_KEY)} — expected 66")
            send_telegram(f"🚨 <b>Bot refused to start</b>\nReason: private key wrong length ({len(PRIVATE_KEY)})")
            sys.exit(1)

        if not WALLET_ADDRESS.startswith("0x") or len(WALLET_ADDRESS) != 42:
            log(f"❌ STARTUP INVARIANT FAILED: wallet address format invalid: {WALLET_ADDRESS}")
            send_telegram("🚨 <b>Bot refused to start</b>\nReason: wallet address format invalid")
            sys.exit(1)

        if WALLET_ADDRESS.lower() != EXPECTED_WALLET.lower():
            log("❌ STARTUP INVARIANT FAILED: wallet mismatch")
            log(f"   Expected: {EXPECTED_WALLET}")
            log(f"   Got:      {WALLET_ADDRESS}")
            send_telegram(f"🚨 <b>Bot refused to start — WALLET MISMATCH</b>\nExpected: {EXPECTED_WALLET[:10]}...\nGot: {WALLET_ADDRESS[:10]}...")
            sys.exit(1)

        state_path = Path(__file__).parent / DEDUP_FILE
        if state_path.exists():
            try:
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
            lev = COIN_LEVERAGE.get(coin, LEVERAGE)
            try:
                set_leverage(self.exchange, coin_hl, lev)
                log(f"  ✅ Leverage {lev}x set for {coin_hl}")
                time.sleep(0.3)
            except Exception as e:
                log(f"  ⚠️  Leverage error {coin}: {e}")

    # ── Position state persistence ────────────────────────────

    def _save_positions_state(self):
        state_path = Path(__file__).parent / POSITIONS_STATE_FILE
        try:
            state = {
                "positions": {},
                "last_exit_candle": self.last_exit_candle,
                "trading_halted": self.trading_halted,
                "halt_reason": self.halt_reason,
                "halted_at": self.halted_at,
                "exit_fail_count": self.exit_fail_count,
                "last_exit_error": self.last_exit_error,
            }
            for coin, pos in self.positions.items():
                state["positions"][coin] = {
                    "coin": pos.coin,
                    "direction": pos.direction,
                    "entry_price": pos.entry_price,
                    "size_usd": pos.size_usd,
                    "size_coin": pos.size_coin,
                    "stop_loss": pos.stop_loss,
                    "initial_sl": pos.initial_sl,
                    "entry_candle": str(pos.entry_candle),
                    "vol_ratio": pos.vol_ratio,
                    "trail_active": pos.trail_active,
                    "best_price": pos.best_price,
                    "entry_time": pos.entry_time.isoformat(),
                }
            state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            log(f"  ⚠️  Could not save positions state: {e}")

    def _load_positions_state(self, has_live_positions: bool = False) -> dict:
        state_path = Path(__file__).parent / POSITIONS_STATE_FILE
        if not state_path.exists():
            return {}
        try:
            data = json.loads(state_path.read_text())
            log("  Loaded positions state file")
            return data
        except Exception as e:
            if has_live_positions:
                log(f"❌ STARTUP ABORT: positions state corrupt while exchange has live positions: {e}")
                send_telegram(
                    f"🚨 <b>Bot refused to start</b>\n"
                    f"Positions state file corrupt and exchange has open positions\n{e}"
                )
                sys.exit(1)
            log(f"  ⚠️  Positions state file corrupt (no live positions, continuing): {e}")
            return {}

    def _validate_trail_state(self, coin, direction, entry_price, best_price, stop_loss):
        """Validate that restored trail state is coherent. Returns True if valid."""
        if direction == "long":
            if best_price < entry_price:
                log(f"  ❌ {coin}: trail incoherent — best_price {best_price:.6f} < entry {entry_price:.6f}")
                return False
            if stop_loss > best_price:
                log(f"  ❌ {coin}: trail incoherent — stop {stop_loss:.6f} > best {best_price:.6f}")
                return False
        else:
            if best_price > entry_price:
                log(f"  ❌ {coin}: trail incoherent — best_price {best_price:.6f} > entry {entry_price:.6f}")
                return False
            if stop_loss < best_price:
                log(f"  ❌ {coin}: trail incoherent — stop {stop_loss:.6f} < best {best_price:.6f}")
                return False
        return True

    def _sync_positions_on_startup(self):
        """Reconcile internal state with exchange positions.

        Uses persisted state (trail info) cross-checked against exchange (authoritative).
        Hard-fails on direction mismatch, entry price drift, size drift, incoherent trail,
        or missing/invalid saved fields.
        Degraded restore (no saved state) is allowed but logged explicitly.
        """
        log("🔄 Reconciling positions on startup...")

        # Fetch live positions first so we know whether to hard-fail on corrupt state
        try:
            live_pos = get_positions()
        except Exception as e:
            log(f"❌ STARTUP ABORT: cannot query exchange positions: {e}")
            send_telegram(f"🚨 <b>Bot refused to start</b>\nCannot query exchange positions\n{e}")
            sys.exit(1)

        saved = self._load_positions_state(has_live_positions=bool(live_pos))
        saved_positions = saved.get("positions", {})
        saved_exit_candle = saved.get("last_exit_candle", {})
        self.last_exit_candle = saved_exit_candle

        self.trading_halted = saved.get("trading_halted", False)
        self.halt_reason = saved.get("halt_reason", "")
        self.halted_at = saved.get("halted_at", "")
        self.exit_fail_count = saved.get("exit_fail_count", {})
        self.last_exit_error = saved.get("last_exit_error", {})
        if self.trading_halted:
            log(f"  🚨 Halt state restored — reason: {self.halt_reason} (since {self.halted_at})")

        # Detect rogue positions not in our coin universe
        known_hl = set(COIN_MAP.values())
        for coin_hl, p in live_pos.items():
            if coin_hl not in known_hl:
                log(f"❌ STARTUP ABORT: unexpected position {coin_hl} {p['direction']} size={p['size']}")
                send_telegram(
                    f"🚨 <b>Bot refused to start — rogue position</b>\n"
                    f"{coin_hl} not in COINS — manual close required"
                )
                sys.exit(1)

        restored = 0
        for coin in COINS:
            coin_hl = COIN_MAP[coin]
            has_live = coin_hl in live_pos
            has_saved = coin in saved_positions

            if not has_live:
                if has_saved:
                    log(f"  ℹ️  {coin}: saved state but no live position — stale, cleared")
                continue

            p = live_pos[coin_hl]
            ep = p["entry_price"]
            direction = p["direction"]
            live_size_coin = abs(p["size"])
            size_usd = live_size_coin * ep

            if has_saved:
                s = saved_positions[coin]

                # Validate saved fields are present and non-zero
                saved_ep = s.get("entry_price")
                if not saved_ep or saved_ep <= 0:
                    log(f"❌ STARTUP ABORT: {coin} saved entry_price missing or invalid: {saved_ep}")
                    send_telegram(f"🚨 <b>Bot refused to start</b>\n{coin}: saved entry_price={saved_ep}")
                    sys.exit(1)

                saved_size_coin = s.get("size_coin")
                if not saved_size_coin or saved_size_coin <= 0:
                    log(f"❌ STARTUP ABORT: {coin} saved size_coin missing or invalid: {saved_size_coin}")
                    send_telegram(f"🚨 <b>Bot refused to start</b>\n{coin}: saved size_coin={saved_size_coin}")
                    sys.exit(1)

                # Validate direction match
                if s["direction"] != direction:
                    log(f"❌ STARTUP ABORT: {coin} direction mismatch saved={s['direction']} exchange={direction}")
                    send_telegram(
                        f"🚨 <b>Bot refused to start — state mismatch</b>\n"
                        f"{coin}: saved {s['direction']} vs exchange {direction}"
                    )
                    sys.exit(1)

                # Validate entry price within tolerance
                if abs(saved_ep - ep) / ep > ENTRY_PRICE_TOLERANCE:
                    log(f"❌ STARTUP ABORT: {coin} entry price drift saved={saved_ep:.6f} exchange={ep:.6f}")
                    send_telegram(
                        f"🚨 <b>Bot refused to start — entry price mismatch</b>\n"
                        f"{coin}: saved {saved_ep:.6f} vs exchange {ep:.6f} (>{ENTRY_PRICE_TOLERANCE*100:.0f}%)"
                    )
                    sys.exit(1)

                # Validate position size within tolerance
                if abs(saved_size_coin - live_size_coin) / saved_size_coin > SIZE_TOLERANCE:
                    log(f"❌ STARTUP ABORT: {coin} size drift saved={saved_size_coin} exchange={live_size_coin}")
                    send_telegram(
                        f"🚨 <b>Bot refused to start — size mismatch</b>\n"
                        f"{coin}: saved {saved_size_coin} vs exchange {live_size_coin} (>{SIZE_TOLERANCE*100:.0f}%)"
                    )
                    sys.exit(1)

                # Validate trail state coherence if trail was active
                trail_active = s.get("trail_active", False)
                best_price = s.get("best_price", saved_ep)
                saved_sl = s["stop_loss"]

                if trail_active:
                    if not self._validate_trail_state(coin, direction, saved_ep, best_price, saved_sl):
                        log(f"❌ STARTUP ABORT: {coin} incoherent trail state in saved data")
                        send_telegram(
                            f"🚨 <b>Bot refused to start — corrupt trail state</b>\n"
                            f"{coin}: trail data failed coherence check"
                        )
                        sys.exit(1)

                # All checks passed — log both saved and live values
                log(
                    f"  ✓ {coin}: checks passed | "
                    f"dir={direction} price saved={saved_ep:.6f} live={ep:.6f} "
                    f"size saved={saved_size_coin} live={live_size_coin}"
                )

                pos = Position(
                    coin=coin,
                    direction=s["direction"],
                    entry_price=saved_ep,
                    size_usd=size_usd,
                    size_coin=live_size_coin,
                    stop_loss=saved_sl,
                    entry_candle=s["entry_candle"],
                    vol_ratio=s["vol_ratio"],
                )
                pos.initial_sl = s.get("initial_sl", pos.stop_loss)
                pos.trail_active = trail_active
                pos.best_price = best_price
                try:
                    pos.entry_time = datetime.fromisoformat(s["entry_time"])
                except Exception:
                    pos.entry_time = datetime.now(timezone.utc)

                self.positions[coin] = pos
                trail_info = f" TRAIL best={pos.best_price:.4f}" if pos.trail_active else ""
                log(f"  🔁 Restored {direction} {coin} @ {ep:.4f} sl={pos.stop_loss:.4f}{trail_info} [persisted]")
                send_telegram(
                    f"🔁 <b>Position restored — {coin} {direction.upper()}</b>\n"
                    f"Entry: {ep:.6f} | SL: {pos.stop_loss:.6f}\n"
                    f"Trail: {'active' if pos.trail_active else 'inactive'}"
                )
                restored += 1
            else:
                # Degraded restore: exchange has position, no saved state.
                # Trail state is lost. Default stop applied.
                sl = ep * (1 - STOP_PCT) if direction == "long" else ep * (1 + STOP_PCT)
                pos = Position(
                    coin=coin,
                    direction=direction,
                    entry_price=ep,
                    size_usd=size_usd,
                    size_coin=live_size_coin,
                    stop_loss=sl,
                    entry_candle="restored",
                    vol_ratio=1.0,
                )
                self.positions[coin] = pos
                log(f"  ⚠️  Restored {direction} {coin} @ {ep:.4f} sl={sl:.4f} [API only — trail state lost]")
                send_telegram(
                    f"⚠️ <b>Position restored (DEGRADED) — {coin} {direction.upper()}</b>\n"
                    f"Entry: {ep:.6f} | SL: {sl:.6f}\n"
                    f"⚠️ No saved state — default {STOP_PCT*100:.0f}% stop"
                )
                restored += 1

        if restored > 0:
            self._save_positions_state()
            log(f"✅ Reconciled {restored} position(s)")
        else:
            log("✅ No open positions — starting clean")

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
        state_path = Path(__file__).parent / "last_entry_candle_2.json"
        try:
            if state_path.exists():
                self.last_entry_candle = json.loads(state_path.read_text())
                log(f"  Loaded entry candle state: {self.last_entry_candle}")
        except Exception as e:
            log(f"  Could not load entry candle state: {e}")

    def _save_entry_candle_state(self):
        state_path = Path(__file__).parent / "last_entry_candle_2.json"
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
            f"price={price:.4f} size=${size_usd:.2f} vol_ratio={vol_ratio:.2f}"
        )

        try:
            resp = place_order(self.exchange, coin_hl, is_buy, size_coin, price)
            log(f"  ✅ Order placed: {resp}")

            # Parse actual fill from exchange response
            try:
                fill_data = resp["response"]["data"]["statuses"][0].get("filled", {})
                filled_size = float(fill_data.get("totalSz", size_coin))
                filled_price = float(fill_data.get("avgPx", price))
            except Exception:
                filled_size = size_coin
                filled_price = price
                log("  ⚠️  Could not parse fill — using requested values")

            filled_usd = filled_size * filled_price
            sl = filled_price * (1 - STOP_PCT) if direction == "long" else filled_price * (1 + STOP_PCT)

            log(
                f"  📋 Fill: size={filled_size} @ {filled_price:.6f} "
                f"(requested: {size_coin:.6f} @ {price:.6f}) sl={sl:.6f}"
            )

            direction_emoji = "🟢" if direction == "long" else "🔴"
            send_telegram(
                f"<b>StochVol WALLET 1 ENTRY — {coin} {direction_emoji} {direction.upper()}</b>\n"
                f"Fill: {filled_price:.6f} | Size: ${filled_usd:.2f}\n"
                f"Stop: {sl:.6f} | Equity: ${equity:.2f}"
            )

            pos = Position(
                coin=coin,
                direction=direction,
                entry_price=filled_price,
                size_usd=filled_usd,
                size_coin=filled_size,
                stop_loss=sl,
                entry_candle=signal["candle_time"],
                vol_ratio=vol_ratio,
            )
            self.positions[coin] = pos
            self.last_entry_candle[coin] = str(signal["candle_time"])
            self._save_entry_candle_state()
            self._save_positions_state()

            log_trade({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "coin": coin,
                "type": "entry",
                "direction": direction,
                "price": round(filled_price, 6),
                "requested_price": round(price, 6),
                "size_usd": round(filled_usd, 2),
                "size_coin": filled_size,
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

        # Use actual exchange size, not modeled size
        try:
            live_pos = get_positions()
            if coin_hl in live_pos:
                size_coin = abs(live_pos[coin_hl]["size"])
            else:
                log(f"  ⚠️  {coin}: no live position on exchange — cleaning up internal state")
                del self.positions[coin]
                self.last_exit_candle[coin] = candle_time
                self.exit_fail_count.pop(coin, None)
                self.last_exit_error.pop(coin, None)
                self._save_positions_state()
                return
        except Exception as e:
            log(f"  ⚠️  {coin}: could not fetch live size ({e}) — using stored size")
            size_coin = pos.size_coin

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

            if pos.direction == "long":
                pnl_usd = (exit_price_for_log - pos.entry_price) * size_coin
            else:
                pnl_usd = (pos.entry_price - exit_price_for_log) * size_coin
            pnl_pct = pnl_usd / pos.size_usd if pos.size_usd > 0 else 0

            log(f"  💰 PnL: {pnl_pct * 100:+.2f}% (${pnl_usd:+.2f})")
            pnl_emoji = "✅" if pnl_usd >= 0 else "❌"
            send_telegram(
                f"<b>StochVol WALLET 1 EXIT — {coin} {pos.direction.upper()}</b>\n"
                f"Reason: {reason}\n"
                f"PnL: {pnl_emoji} ${pnl_usd:+.2f} ({pnl_pct*100:+.2f}%)\n"
                f"Equity: ${self.equity:.2f}"
            )

            log_trade({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "coin": coin,
                "type": "exit",
                "direction": pos.direction,
                "price": round(exit_price_for_log, 6),
                "price_source": exit_price_source,
                "size_usd": round(pos.size_usd, 2),
                "size_coin": size_coin,
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
            self.exit_fail_count.pop(coin, None)
            self.last_exit_error.pop(coin, None)
            self._save_positions_state()

        except Exception as e:
            log(f"  ❌ Exit error {coin}: {e}")
            traceback.print_exc()
            # If position was liquidated or closed on exchange, clean up state
            try:
                recheck = get_positions()
                if coin_hl not in recheck:
                    log(f"  ⚠️  {coin}: position gone from exchange after failed exit — cleaning up")
                    del self.positions[coin]
                    self.last_exit_candle[coin] = candle_time
                    self.exit_fail_count.pop(coin, None)
                    self.last_exit_error.pop(coin, None)
                    self._save_positions_state()
                    return
            except Exception:
                pass
            # Track consecutive failures and halt if threshold reached
            self.exit_fail_count[coin] = self.exit_fail_count.get(coin, 0) + 1
            self.last_exit_error[coin] = str(e)
            count = self.exit_fail_count[coin]
            log(f"  ⚠️  {coin}: consecutive exit failure #{count}/{MAX_EXIT_RETRIES}")
            if count >= MAX_EXIT_RETRIES:
                self.trading_halted = True
                self.halt_reason = f"{count} consecutive exit failures on {coin}"
                self.halted_at = datetime.now(timezone.utc).isoformat()
                self._save_positions_state()
                log(f"  🚨 TRADING HALTED — {count} consecutive exit failures on {coin}")
                send_telegram(
                    f"🚨 <b>WALLET 1 TRADING HALTED</b>\n"
                    f"Reason: {self.halt_reason}\n"
                    f"Last error: {e}\n"
                    f"Action required: manual intervention"
                )
                self.halt_alert_sent = True

    def run_once(self):
        equity = self._get_equity()
        log(f"\n{'=' * 55}")
        log(f"  💰 Equity: ${equity:.2f} | Positions: {list(self.positions.keys())}")
        log(f"{'=' * 55}")

        if self.trading_halted:
            log(f"  🚨 HALTED — entries disabled | {self.halt_reason}")
            if not self.halt_alert_sent:
                send_telegram(
                    f"🚨 <b>WALLET 1 STILL HALTED</b>\n"
                    f"Reason: {self.halt_reason}\n"
                    f"Since: {self.halted_at}\n"
                    f"Manual intervention required"
                )
                self.halt_alert_sent = True

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
                        self._exit_trade(coin, reason, current_price, candle_time)
                    elif signal_exit:
                        self._exit_trade(coin, "signal_exit", current_price, candle_time)

                # ── Check for new entry ───────────────────────
                if coin not in self.positions:
                    if self.trading_halted:
                        continue

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
                send_telegram(f"⚠️ StochVol WALLET 1 ERROR — {coin}\n{str(e)}")
                traceback.print_exc()

        # Persist trail stop updates
        if self.positions:
            self._save_positions_state()

        # Shadow basket evaluation
        if BASKET_SHADOW and shadow_candidates:
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

    def run(self):
        log("🚀 StochVol V4 (wallet 1) executor running. Ctrl+C or pkill to stop.")
        send_telegram("🤖 <b>StochVol V4 — WALLET 1 started</b>\nServer: Legatus | Coins: " + ", ".join(COINS))
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


if __name__ == "__main__":
    executor = StochVolExecutor()
    executor.run()

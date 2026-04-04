# =============================================================
# live/executor.py — EMA16 V8A Live Trading Bot
# =============================================================
import os
import sys
import time
import csv
import logging
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

from live.data_feed     import DataFeed, COIN_MAP
from live.signal_engine import SignalEngine

PAPER_MODE   = False
INITIAL_CAP  = 50.0
RISK_PCT     = 0.005
STOP_PCT     = 0.02
LEVERAGE     = 5
COINS        = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]
LOOP_SECONDS = 300
MIN_NOTIONAL  = 11.0
TRADES_CSV    = Path("live/trades_live.csv")
CSV_HEADERS   = ["timestamp","coin","side","action","size","entry_price",
                 "exit_price","pnl_usd","fee_usd","exit_reason","equity_after"]
API_URL      = "https://api.hyperliquid.xyz"

HL_COINS = {k: COIN_MAP[k] for k in COINS}

SZ_DECIMALS = {
    "PEPE": 0, "SOL": 2, "AAVE": 2, "DOGE": 0,
    "LINK": 1, "ETH": 4, "XRP": 0,
}

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1855483522")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("live/trading.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

def send_telegram(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        log.warning(f"Telegram error: {e}")

def round_size(size: float, coin: str) -> float:
    decimals = SZ_DECIMALS.get(coin, 2)
    q = Decimal("1") if decimals == 0 else Decimal("1e-" + str(decimals))
    return float(Decimal(str(size)).quantize(q, rounding=ROUND_DOWN))

def round_perp_price(px: float, coin: str) -> float:
    sz_dec = SZ_DECIMALS.get(coin, 2)
    d = Decimal(str(px))
    if d == 0:
        return 0.0
    max_decimals = max(0, 6 - sz_dec)
    if d == d.to_integral_value():
        return float(d.quantize(Decimal("1")))
    adjusted = d.adjusted()
    decimals = min(max_decimals, max(0, 4 - adjusted))
    q = Decimal("1") if decimals == 0 else Decimal("1e-" + str(decimals))
    return float(d.quantize(q, rounding=ROUND_DOWN))

def init_csv():
    if not TRADES_CSV.exists():
        with open(TRADES_CSV, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADERS)

def log_trade(coin, side, action, size, entry_price,
              exit_price, pnl_usd, fee_usd, exit_reason, equity_after):
    try:
        with open(TRADES_CSV, "a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                coin, side, action, size,
                round(entry_price, 6),
                round(exit_price, 6) if exit_price else "",
                round(pnl_usd, 4) if pnl_usd is not None else "",
                round(fee_usd, 4) if fee_usd is not None else "",
                exit_reason or "",
                round(equity_after, 2),
            ])
    except Exception as e:
        log.warning(f"CSV log error: {e}")

def get_exchange():
    from hyperliquid.exchange import Exchange
    from hyperliquid.info     import Info
    from eth_account          import Account
    private_key    = os.getenv("HL_PRIVATE_KEY")
    wallet_address = os.getenv("HL_WALLET_ADDRESS")
    if not private_key or not wallet_address:
        raise ValueError("Missing HL_PRIVATE_KEY or HL_WALLET_ADDRESS in .env")
    account  = Account.from_key(private_key)
    exchange = Exchange(account, API_URL)
    info     = Info(API_URL)
    return exchange, info, wallet_address

def get_equity(wallet_address: str) -> float:
    r = requests.post(f"{API_URL}/info",
        json={"type": "spotClearinghouseState", "user": wallet_address},
        headers={"Content-Type": "application/json"}, timeout=5)
    for b in r.json().get("balances", []):
        if b["coin"] == "USDC":
            return float(b["total"])
    return 0.0

def get_live_positions(wallet_address: str) -> dict:
    r = requests.post(f"{API_URL}/info",
        json={"type": "clearinghouseState", "user": wallet_address},
        headers={"Content-Type": "application/json"}, timeout=5)
    data = r.json()
    positions = {}
    hl_to_bt = {v: k for k, v in HL_COINS.items()}
    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        hl_coin = p.get("coin")
        bt_coin = hl_to_bt.get(hl_coin)
        if not bt_coin:
            continue
        szi = float(p.get("szi", 0))
        if szi == 0:
            continue
        entry = p.get("entryPx")
        if entry is None:
            continue
        positions[bt_coin] = {
            "side":    "long" if szi > 0 else "short",
            "size":    abs(szi),
            "entry":   float(entry),
            "hl_coin": hl_coin,
        }
    return positions

def get_mid_price(hl_coin: str) -> float:
    r = requests.post(f"{API_URL}/info",
        json={"type": "allMids"},
        headers={"Content-Type": "application/json"}, timeout=5)
    return float(r.json().get(hl_coin, 0))

def place_order(exchange, coin: str, side: str, size: float) -> dict:
    hl_coin = HL_COINS[coin]
    is_buy  = side == "buy"
    if PAPER_MODE:
        log.info(f"  [PAPER] {side.upper()} {size} {hl_coin}")
        return {"status": "paper"}
    mid      = get_mid_price(hl_coin)
    raw_px   = mid * 1.01 if is_buy else mid * 0.99
    limit_px = round_perp_price(raw_px, coin)
    if size * limit_px < MIN_NOTIONAL:
        log.warning(f"  {coin} notional ${size*limit_px:.2f} < ${MIN_NOTIONAL} — skipping")
        return {"status": "skipped", "reason": "min_notional"}
    result = exchange.order(
        hl_coin, is_buy, size, limit_px,
        {"limit": {"tif": "Ioc"}},
    )
    log.info(f"  ORDER: {side.upper()} {size} {hl_coin} @ {limit_px} → {result}")
    if isinstance(result, dict) and result.get("status") == "err":
        raise RuntimeError(f"Order rejected: {result.get('response')}")
    statuses = result.get("response", {}).get("data", {}).get("statuses", [])
    if statuses and "error" in statuses[0]:
        raise RuntimeError(f"Order fill error: {statuses[0]['error']}")
    return result

def close_position(exchange, coin: str, position: dict) -> dict:
    side = "sell" if position["side"] == "long" else "buy"
    return place_order(exchange, coin, side, position["size"])

def set_leverage(exchange, coin: str):
    if PAPER_MODE:
        return
    try:
        exchange.update_leverage(LEVERAGE, HL_COINS[coin], is_cross=True)
    except Exception as e:
        log.warning(f"Could not set leverage for {coin}: {e}")

class TradingBot:

    def __init__(self):
        self.feed              = DataFeed()
        self.engine            = SignalEngine()
        self.positions         = {}
        self.best_prices       = {}
        self.trail_active      = {}
        self.last_entry_candle = {}
        self.last_exit_candle  = {}
        if not PAPER_MODE:
            self.exchange, self.info, self.wallet = get_exchange()
            log.info(f"Connected — wallet: {self.wallet}")
        else:
            self.exchange = self.info = self.wallet = None
        init_csv()

    def sync_positions_on_startup(self):
        if PAPER_MODE:
            return
        try:
            live = get_live_positions(self.wallet)
            for coin, pos in live.items():
                sl = (pos["entry"] * (1 + STOP_PCT) if pos["side"] == "short"
                      else pos["entry"] * (1 - STOP_PCT))
                self.positions[coin]    = {**pos, "stop_loss": sl}
                self.best_prices[coin]  = pos["entry"]
                self.trail_active[coin] = False
                log.info(f"  Restored: {coin} {pos['side']} size={pos['size']} entry={pos['entry']}")
            for coin in list(self.positions.keys()):
                if coin not in live:
                    self.positions.pop(coin, None)
                    self.best_prices.pop(coin, None)
                    self.trail_active.pop(coin, None)
        except Exception as e:
            log.error(f"Startup sync error: {e}")

    def sync_positions(self):
        if PAPER_MODE:
            return
        try:
            live = get_live_positions(self.wallet)
            for coin in list(self.positions.keys()):
                if coin not in live:
                    log.info(f"  {coin} closed externally — removing")
                    self.positions.pop(coin, None)
                    self.best_prices.pop(coin, None)
                    self.trail_active.pop(coin, None)
        except Exception as e:
            log.warning(f"sync_positions error: {e}")

    def compute_size(self, equity: float, coin: str):
        dollar_risk = equity * RISK_PCT
        pos_usd     = dollar_risk / STOP_PCT
        mid         = get_mid_price(HL_COINS[coin])
        size        = round_size(pos_usd / mid, coin)
        return size, mid

    def update_trail_stop(self, coin: str, price: float, position: dict):
        p     = self.engine.params
        side  = position["side"]
        entry = position["entry"]
        if side == "long":
            best = max(self.best_prices.get(coin, price), price)
            self.best_prices[coin] = best
            profit_pct = (best - entry) / entry
        else:
            best = min(self.best_prices.get(coin, price), price)
            self.best_prices[coin] = best
            profit_pct = (entry - best) / entry
        if profit_pct >= p["trail_trigger"]:
            self.trail_active[coin] = True
        if not self.trail_active.get(coin):
            return None
        offset = (p["trail_tight_offset"] if profit_pct >= p["trail_tight_trigger"]
                  else p["trail_offset"])
        return (best * (1 - offset) if side == "long" else best * (1 + offset))

    def run_once(self):
        log.info("─" * 60)
        log.info(f"Loop at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        self.sync_positions()
        equity = get_equity(self.wallet) if not PAPER_MODE else INITIAL_CAP
        log.info(f"Equity: ${equity:.2f} | Positions: {list(self.positions.keys())}")

        for coin in COINS:
            try:
                df     = self.feed.get_candles(coin)
                signal = self.engine.get_signal(coin, df)
                action = signal["action"]
                price  = signal["entry_price"]
                log.info(f"  {coin:<6} action={str(action):<12} "
                         f"rsi={signal['rsi']:.1f}  price={price:.6f}  "
                         f"candle={signal['candle_time'][:16]}")
                in_pos = coin in self.positions

                if in_pos:
                    pos      = self.positions[coin]
                    new_stop = self.update_trail_stop(coin, price, pos)
                    if new_stop:
                        pos["stop_loss"] = new_stop
                    stop_hit = (
                        (pos["side"] == "long"  and price <= pos.get("stop_loss", 0)) or
                        (pos["side"] == "short" and price >= pos.get("stop_loss", float("inf")))
                    )
                    sig_exit = (
                        (pos["side"] == "long"  and action in ("short", "exit_long")) or
                        (pos["side"] == "short" and action in ("long",  "exit_short"))
                    )
                    if stop_hit or sig_exit:
                        reason = "stop" if stop_hit else "signal"
                        log.info(f"  EXIT {coin} {pos['side']} reason={reason}")
                        exit_px = price
                        if pos["side"] == "long":
                            pnl = (exit_px - pos["entry"]) / pos["entry"] * pos["size"] * exit_px
                        else:
                            pnl = (pos["entry"] - exit_px) / pos["entry"] * pos["size"] * exit_px
                        fee = pos["size"] * exit_px * 0.000432
                        equity_now = get_equity(self.wallet) if not PAPER_MODE else INITIAL_CAP
                        log_trade(coin, pos["side"], "close", pos["size"],
                                  pos["entry"], exit_px, pnl, fee, reason, equity_now)
                        close_position(self.exchange, coin, pos)
                        pnl_emoji = "✅" if pnl >= 0 else "❌"
                        send_telegram(
                            f"<b>EMA16 EXIT — {coin} {pos['side'].upper()}</b>\n"
                            f"Reason: {reason}\n"
                            f"Entry: {pos['entry']:.6f} → Exit: {exit_px:.6f}\n"
                            f"PnL: {pnl_emoji} ${pnl:.2f} | Equity: ${equity_now:.2f}"
                        )
                        self.positions.pop(coin)
                        self.best_prices.pop(coin, None)
                        self.trail_active.pop(coin, None)
                        self.last_exit_candle[coin] = signal["candle_time"]
                        in_pos = False
                        continue

                current_candle = signal["candle_time"]
                if self.last_entry_candle.get(coin) == current_candle:
                    continue
                if self.last_exit_candle.get(coin) == current_candle:
                    continue

                if not in_pos and action in ("long", "short"):
                    size, mid = self.compute_size(equity, coin)
                    if size <= 0 or size * mid < MIN_NOTIONAL:
                        log.warning(f"  {coin} skipped — size={size} notional=${size*mid:.2f}")
                        continue
                    set_leverage(self.exchange, coin)
                    result = place_order(self.exchange, coin,
                                         "buy" if action == "long" else "sell", size)
                    if result.get("status") == "skipped":
                        continue
                    sl = (signal["stop_loss_long"] if action == "long"
                          else signal["stop_loss_short"])
                    self.positions[coin] = {
                        "side": action, "size": size, "entry": mid, "stop_loss": sl,
                    }
                    self.best_prices[coin]  = mid
                    self.trail_active[coin] = False
                    self.last_entry_candle[coin] = signal["candle_time"]
                    equity_now = get_equity(self.wallet) if not PAPER_MODE else INITIAL_CAP
                    log_trade(coin, action, "open", size, mid, None, None, None, None, equity_now)
                    log.info(f"  ENTER {coin} {action} size={size} price={mid:.6f} sl={sl:.6f}")
                    direction = "🟢 LONG" if action == "long" else "🔴 SHORT"
                    send_telegram(
                        f"<b>EMA16 ENTRY — {coin} {direction}</b>\n"
                        f"Price: {mid:.6f} | Size: {size}\n"
                        f"Stop: {sl:.6f} | Equity: ${equity_now:.2f}"
                    )

            except Exception as e:
                log.error(f"  {coin} ERROR: {e}", exc_info=True)
                send_telegram(f"⚠️ EMA16 ERROR — {coin}\n{str(e)}")

    def run(self):
        log.info("=" * 60)
        log.info("EMA16 V8A Bot — Starting")
        log.info(f"Mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
        log.info(f"Coins: {COINS}")
        log.info(f"Capital ref: ${INITIAL_CAP} | Risk: {RISK_PCT*100}%")
        log.info("=" * 60)
        self.sync_positions_on_startup()
        send_telegram("🤖 <b>EMA16 V8A Bot started</b>\nServer: Legatus | Coins: " + ", ".join(COINS))
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                log.info("Bot stopped.")
                send_telegram("🛑 EMA16 V8A Bot stopped.")
                break
            except Exception as e:
                log.error(f"Loop error: {e}", exc_info=True)
                send_telegram(f"⚠️ EMA16 loop error: {str(e)}")
            log.info(f"Sleeping {LOOP_SECONDS}s...")
            time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()

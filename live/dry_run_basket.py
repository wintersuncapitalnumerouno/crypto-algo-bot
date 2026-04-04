"""
Dry-run: fetch real signals, run through basket optimizer. No orders placed.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from live.basket_optimizer import build_entry_basket, log_basket
from live.signal_engine_stochvol import StochVolSignalEngine
from live.data_feed import DataFeed

COINS  = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]
EQUITY = 51.30

feed   = DataFeed()
engine = StochVolSignalEngine()

candidates = []
for coin in COINS:
    df_5m = feed.get_candles(coin)
    sig   = engine.get_signal(coin, df_5m)
    sig["coin"] = coin
    action = sig.get("action")
    print(
        f"  {coin:<5} action={str(action):<6} "
        f"vol={sig.get('vol_ratio', 0):.2f} "
        f"K={sig.get('stoch_k', 0):.1f} "
        f"D={sig.get('stoch_d', 0):.1f} "
        f"price={sig.get('price', 0):.4f} "
        f"sl={sig.get('stop_loss', 0):.4f}"
    )
    if action in ("long", "short"):
        candidates.append(sig)

print(f"\n  {len(candidates)} candidates with active signals\n")
allocations = build_entry_basket(candidates, EQUITY, open_positions={})
log_basket(allocations)


from pathlib import Path

path = Path("/Users/javierlepianireyes/Desktop/crypto-algo-bot/live/executor_stochvol.py")
text = path.read_text()

# 1) import
needle = "from live.basket_optimizer import build_entry_basket, log_basket"
if needle not in text:
    anchor = "from hyperliquid.exchange import Exchange"
    if anchor not in text:
        raise SystemExit("Import anchor not found")
    text = text.replace(anchor, anchor + "\nfrom live.basket_optimizer import build_entry_basket, log_basket", 1)

# 2) flag
if "BASKET_SHADOW = True" not in text:
    anchor = "MIN_NOTIONAL"
    idx = text.find(anchor)
    line_end = text.find("\n", idx)
    text = text[:line_end+1] + "BASKET_SHADOW = True\n" + text[line_end+1:]

# 3) init collector before loop
old3 = """        for coin in COINS:
            try:
                df_5m = self.feed.get_candles(coin)
                signal = self.engine.get_signal(coin, df_5m)"""
new3 = """        shadow_candidates = []

        for coin in COINS:
            try:
                df_5m = self.feed.get_candles(coin)
                signal = self.engine.get_signal(coin, df_5m)"""
if old3 not in text:
    raise SystemExit("Loop anchor not found")
text = text.replace(old3, new3, 1)

# 4) collect in loop using same signal
old4 = """                if coin not in self.positions:
                    action = signal.get("action")

                    if self.last_entry_candle.get(coin) == str(candle_time):"""
new4 = """                if coin not in self.positions:
                    action = signal.get("action")

                    if action in ("long", "short"):
                        _s = dict(signal)
                        _s["coin"] = coin
                        shadow_candidates.append(_s)

                    if self.last_entry_candle.get(coin) == str(candle_time):"""
if old4 not in text:
    raise SystemExit("Entry block anchor not found")
text = text.replace(old4, new4, 1)

# 5) log after loop — find exact tail anchor first
import re
for line in text.split("\n"):
    if "Error" in line and "coin" in line and "except" not in line:
        print("CANDIDATE:", repr(line))

# Try both known variants
old5a = """            except Exception as e:
                log(f"  \u274c Exit error {coin}: {e}")
                traceback.print_exc()"""
old5b = """            except Exception as e:
                log(f"  \u274c Error {coin}: {e}")
                traceback.print_exc()"""

old5 = old5a if old5a in text else (old5b if old5b in text else None)
if old5 is None:
    raise SystemExit("Tail anchor not found — check Exit error line")

new5 = old5 + """

        if BASKET_SHADOW:
            try:
                shadow_allocs = build_entry_basket(shadow_candidates, equity, self.positions)
                if shadow_allocs:
                    log(f"  [SHADOW] Basket would select {len(shadow_allocs)} candidates")
                    for a in shadow_allocs:
                        log(f"    [SHADOW] {a[chr(39)+'coin'+chr(39)]:<6} score={a[chr(39)+'score'+chr(39)]:.3f} size=${a[chr(39)+'size_usd'+chr(39)]:.2f} risk=${a[chr(39)+'risk_usd'+chr(39)]:.4f} stop={a[chr(39)+'stop_pct'+chr(39)]*100:.2f}%")
                else:
                    log("  [SHADOW] Basket: no candidates passed constraints")
            except Exception as e:
                log(f"  [SHADOW] Basket optimizer error: {e}")"""

text = text.replace(old5, new5, 1)
path.write_text(text)
print("Shadow mode injected safely")

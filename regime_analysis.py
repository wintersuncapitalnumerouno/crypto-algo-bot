"""
regime_analysis.py
Loads all 7 coin trades from a STOCHVOL_V3 backtest run and segments
performance by market regime, ADX level, and direction.

Usage:
    python regime_analysis.py

Edit RUN_FOLDER below to point to your target run.
"""

import pandas as pd
import numpy as np
import sqlite3
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
RUN_FOLDER = Path(
    "/Users/javierlepianireyes/Desktop/crypto-algo-bot/results/exploration"
    "/STOCHVOL_V3/stochvol_v3_wider/20260330_1231_20240330_20260330"
)
DB_PATH = Path("/Users/javierlepianireyes/Desktop/crypto-algo-bot/data/candles.db")
COINS   = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]
ATR_PERIOD  = 14
ATR_LOOKBACK = 50   # rolling window to compute "avg ATR" for vol regime

# ── Load trades ───────────────────────────────────────────────────────────────
frames = []
for coin in COINS:
    f = RUN_FOLDER / f"{coin}_5m" / "trades.csv"
    if not f.exists():
        print(f"  ⚠️  Missing: {f}")
        continue
    df = pd.read_csv(f, parse_dates=["entry_time", "exit_time"])
    df["coin"] = coin
    frames.append(df)

trades = pd.concat(frames, ignore_index=True)
print(f"\n✅ Loaded {len(trades):,} trades across {len(frames)} coins")
print(f"   Date range: {trades['entry_time'].min().date()} → {trades['entry_time'].max().date()}")

# ── Add ATR vol regime from candle DB ─────────────────────────────────────────
def get_atr_regime(trades_df, db_path, atr_period=14, lookback=50):
    """Join ATR data from SQLite candle DB to trades."""
    if not db_path.exists():
        print(f"  ⚠️  DB not found at {db_path}, skipping ATR regime")
        trades_df["atr_regime"] = "unknown"
        trades_df["atr_ratio"]  = np.nan
        return trades_df

    conn = sqlite3.connect(db_path)

    vol_regimes = []
    atr_ratios  = []

    for _, row in trades_df.iterrows():
        coin = row["coin"]
        ts   = row["entry_time"]

        try:
            # fetch candles up to entry time
            q = f"""
                SELECT high, low, close FROM candles
                WHERE coin = '{coin}' AND timeframe = '5m'
                  AND timestamp <= '{ts}'
                ORDER BY timestamp DESC
                LIMIT {lookback + atr_period + 1}
            """
            candles = pd.read_sql_query(q, conn)
            if len(candles) < atr_period + 2:
                vol_regimes.append("unknown")
                atr_ratios.append(np.nan)
                continue

            candles = candles.iloc[::-1].reset_index(drop=True)
            hl  = candles["high"] - candles["low"]
            hpc = (candles["high"] - candles["close"].shift(1)).abs()
            lpc = (candles["low"]  - candles["close"].shift(1)).abs()
            tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
            atr = tr.rolling(atr_period).mean()

            cur_atr  = atr.iloc[-1]
            avg_atr  = atr.iloc[-lookback:].mean()
            ratio    = cur_atr / avg_atr if avg_atr > 0 else np.nan

            if pd.isna(ratio):
                vol_regimes.append("unknown")
            elif ratio >= 1.3:
                vol_regimes.append("high_vol")
            elif ratio <= 0.7:
                vol_regimes.append("low_vol")
            else:
                vol_regimes.append("normal_vol")
            atr_ratios.append(round(ratio, 3) if not pd.isna(ratio) else np.nan)

        except Exception:
            vol_regimes.append("unknown")
            atr_ratios.append(np.nan)

    conn.close()
    trades_df["atr_regime"] = vol_regimes
    trades_df["atr_ratio"]  = atr_ratios
    return trades_df


print("\n🔄 Computing ATR vol regime (this may take ~30s)...")
trades = get_atr_regime(trades, DB_PATH)

# ── ADX regime bucketing ──────────────────────────────────────────────────────
def adx_bucket(adx):
    if pd.isna(adx) or adx == 0:
        return "no_adx"
    elif adx < 15:
        return "ranging (<15)"
    elif adx < 25:
        return "mild_trend (15-25)"
    else:
        return "trending (>25)"

trades["adx_regime"] = trades["adx_at_entry"].apply(adx_bucket)

# ── Helper: stats for a slice ─────────────────────────────────────────────────
def stats(df, label=""):
    n  = len(df)
    if n == 0:
        return {"label": label, "trades": 0}
    wr  = (df["pnl_pct"] > 0).mean() * 100
    avg_r   = df["r_multiple"].mean()
    avg_pnl = df["pnl_pct"].mean()
    pf_wins = df.loc[df["pnl_pct"] > 0, "pnl_pct"].sum()
    pf_loss = df.loc[df["pnl_pct"] < 0, "pnl_pct"].abs().sum()
    pf  = pf_wins / pf_loss if pf_loss > 0 else np.inf
    sl_pct = (df["exit_reason"] == "stop_loss").mean() * 100
    return {
        "label":    label,
        "trades":   n,
        "win_rate": round(wr, 1),
        "avg_R":    round(avg_r, 3),
        "avg_pnl%": round(avg_pnl, 3),
        "prof_factor": round(pf, 2),
        "sl_rate%": round(sl_pct, 1),
    }

def print_table(rows, title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    if not rows:
        print("  No data")
        return
    keys = list(rows[0].keys())
    widths = {k: max(len(k), max(len(str(r[k])) for r in rows)) for k in keys}
    header = "  " + "  ".join(k.ljust(widths[k]) for k in keys)
    print(header)
    print("  " + "-" * (sum(widths.values()) + 2 * len(keys)))
    for r in rows:
        print("  " + "  ".join(str(r[k]).ljust(widths[k]) for k in keys))


# ── 1. HTF Trend ──────────────────────────────────────────────────────────────
rows = []
for regime in ["up", "down", "sideways", "flat"]:
    sl = trades[trades["htf_trend"] == regime]
    if len(sl) > 0:
        rows.append(stats(sl, f"htf={regime}"))
print_table(rows, "1. Performance by HTF Trend")

# ── 2. ADX regime ─────────────────────────────────────────────────────────────
rows = []
for regime in sorted(trades["adx_regime"].unique()):
    sl = trades[trades["adx_regime"] == regime]
    rows.append(stats(sl, regime))
print_table(rows, "2. Performance by ADX Regime")

# ── 3. Direction ─────────────────────────────────────────────────────────────
rows = []
for d in ["long", "short"]:
    sl = trades[trades["direction"] == d]
    rows.append(stats(sl, d))
print_table(rows, "3. Long vs Short")

# ── 4. HTF trend × Direction ─────────────────────────────────────────────────
rows = []
for trend in ["up", "down"]:
    for d in ["long", "short"]:
        sl = trades[(trades["htf_trend"] == trend) & (trades["direction"] == d)]
        if len(sl) >= 10:
            rows.append(stats(sl, f"htf={trend} + {d}"))
print_table(rows, "4. HTF Trend × Direction (aligned vs counter-trend)")

# ── 5. ADX × HTF trend ───────────────────────────────────────────────────────
rows = []
for adx in ["ranging (<15)", "mild_trend (15-25)", "trending (>25)"]:
    for trend in ["up", "down"]:
        sl = trades[(trades["adx_regime"] == adx) & (trades["htf_trend"] == trend)]
        if len(sl) >= 10:
            rows.append(stats(sl, f"{adx} + {trend}"))
print_table(rows, "5. ADX × HTF Trend")

# ── 6. ATR vol regime (if available) ─────────────────────────────────────────
if trades["atr_regime"].ne("unknown").any():
    rows = []
    for regime in ["low_vol", "normal_vol", "high_vol"]:
        sl = trades[trades["atr_regime"] == regime]
        if len(sl) >= 10:
            rows.append(stats(sl, regime))
    print_table(rows, "6. ATR Vol Regime")
else:
    print("\n  ℹ️  ATR regime skipped (DB not found or no data)")

# ── 7. Per-coin summary ───────────────────────────────────────────────────────
rows = []
for coin in COINS:
    sl = trades[trades["coin"] == coin]
    if len(sl) > 0:
        rows.append(stats(sl, coin))
print_table(rows, "7. Per-coin Summary")

# ── 8. Exit reason breakdown ─────────────────────────────────────────────────
rows = []
for reason in trades["exit_reason"].unique():
    sl = trades[trades["exit_reason"] == reason]
    rows.append(stats(sl, reason))
print_table(rows, "8. Exit Reason Breakdown")

# ── 9. R-multiple distribution ────────────────────────────────────────────────
print(f"\n{'='*70}")
print("  9. R-multiple Distribution")
print(f"{'='*70}")
bins = [(-99,-1), (-1,-0.5), (-0.5,0), (0,0.5), (0.5,1), (1,2), (2,5), (5,99)]
for lo, hi in bins:
    sl = trades[(trades["r_multiple"] >= lo) & (trades["r_multiple"] < hi)]
    pct = len(sl) / len(trades) * 100
    bar = "█" * int(pct / 2)
    print(f"  [{lo:>4} to {hi:<4}]  {len(sl):>5} trades  {pct:>5.1f}%  {bar}")

# ── 10. Best and worst conditions ─────────────────────────────────────────────
print(f"\n{'='*70}")
print("  10. Top conditions by win rate (min 30 trades)")
print(f"{'='*70}")
results = []
for coin in COINS:
    for trend in trades["htf_trend"].unique():
        for adx in trades["adx_regime"].unique():
            sl = trades[
                (trades["coin"] == coin) &
                (trades["htf_trend"] == trend) &
                (trades["adx_regime"] == adx)
            ]
            if len(sl) >= 30:
                s = stats(sl)
                s["label"] = f"{coin} | htf={trend} | {adx}"
                results.append(s)

results.sort(key=lambda x: x["win_rate"], reverse=True)
for r in results[:10]:
    print(f"  {r['label']:<45}  WR={r['win_rate']}%  R={r['avg_R']}  n={r['trades']}")

print(f"\n{'='*70}")
print("  Worst conditions (most stop losses)")
print(f"{'='*70}")
results.sort(key=lambda x: x["sl_rate%"], reverse=True)
for r in results[:10]:
    print(f"  {r['label']:<45}  SL%={r['sl_rate%']}%  WR={r['win_rate']}%  n={r['trades']}")

print("\n✅ Done\n")

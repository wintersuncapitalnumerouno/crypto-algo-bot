import sys, os, pandas as pd, numpy as np
from pathlib import Path
from tabulate import tabulate
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from data.fetch_data import load_candles

INTERVAL_MINUTES = {"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440}

def validate_coin(coin, interval):
    r = {"coin":coin,"interval":interval,"status":"✅ PASS","candles":0,"from":"N/A","to":"N/A","gaps":0,"nan_rows":0,"bad_ohlc":0,"zero_vol":0,"issues":[]}
    try:
        df = load_candles(coin, interval)
    except FileNotFoundError:
        r["status"] = "❌ MISSING"; r["issues"].append("run fetch_data.py first"); return r
    if df.empty:
        r["status"] = "❌ EMPTY"; return r
    r["candles"] = len(df)
    r["from"] = str(df.index[0])[:19]
    r["to"]   = str(df.index[-1])[:19]
    nan_count = df[["open","high","low","close","volume"]].isna().any(axis=1).sum()
    if nan_count: r["nan_rows"]=nan_count; r["issues"].append(f"{nan_count} NaN rows")
    bad_ohlc = ((df["high"]<df["low"]) | (df["open"]>df["high"]) | (df["close"]>df["high"])).sum()
    if bad_ohlc: r["bad_ohlc"]=bad_ohlc; r["issues"].append(f"{bad_ohlc} bad OHLC rows")
    zero_vol = (df["volume"]==0).sum()
    r["zero_vol"] = zero_vol
    if zero_vol/len(df)>0.05: r["issues"].append(f"{zero_vol} zero-vol candles ({zero_vol/len(df)*100:.1f}%)")
    exp_gap = INTERVAL_MINUTES.get(interval,5)*60
    diffs = df.index.to_series().diff().dt.total_seconds().dropna()
    gaps = diffs[diffs > exp_gap*2]
    r["gaps"] = len(gaps)
    if len(gaps): r["issues"].append(f"{len(gaps)} gaps (biggest {gaps.max()/3600:.1f}h)")
    if df.index.duplicated().sum(): r["issues"].append("duplicate timestamps")
    spikes = (df["close"].pct_change().abs()>0.20).sum()
    if spikes: r["issues"].append(f"{spikes} candles >20% move")
    if r["issues"]: r["status"] = "⚠️  WARN" if len(r["issues"])<=2 else "❌ FAIL"
    return r

if __name__ == "__main__":
    print("="*65)
    print("  🔍 Data Quality Validator")
    print("="*65)
    results, issues = [], []
    for coin in config.COINS:
        for interval in config.TIMEFRAMES:
            r = validate_coin(coin, interval)
            results.append(r)
            for i in r["issues"]: issues.append(f"  {coin} {interval}: {i}")
    rows = [[r["status"],r["coin"],r["interval"],
             f"{r['candles']:,}" if r["candles"] else "—",
             r["from"][:10] if r["from"]!="N/A" else "—",
             r["to"][:10]   if r["to"]!="N/A"   else "—",
             r["gaps"]    or "✓",
             r["nan_rows"] or "✓",
             r["zero_vol"] or "✓"] for r in results]
    print(tabulate(rows, headers=["Status","Coin","TF","Candles","From","To","Gaps","NaNs","ZeroVol"], tablefmt="rounded_outline"))
    if issues:
        print(f"\n⚠️  Issues ({len(issues)}):")
        for i in issues: print(i)
    else:
        print("\n✅ All data passed — looks clean!")

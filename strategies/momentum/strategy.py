import pandas as pd
from strategies.momentum.params     import get_default_params
from strategies.momentum.indicators import populate_indicators
from strategies.momentum.logic      import generate_entries, generate_exits

def get_entries_exits(df, params=None):
    p = {**get_default_params(), **(params or {})}
    df_15m = df.resample("15min").agg({
        "open": "first", "high": "max",
        "low": "min", "close": "last", "volume": "sum",
    }).dropna()
    df_15m = populate_indicators(df_15m, p)
    df_15m = generate_entries(df_15m, p)
    df_15m = generate_exits(df_15m, p)
    warmup = max(p["slow_ema"] * 2, p["htf_ema"])
    df_15m = df_15m.iloc[warmup:].copy()
    long_entries  = df_15m["signal"] == 1
    short_entries = df_15m["signal"] == -1
    return long_entries, short_entries, short_entries, long_entries, df_15m

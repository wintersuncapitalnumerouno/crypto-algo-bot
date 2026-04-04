rm -rf strategies/trend# strategies/ema16/strategy.py
import pandas as pd
from strategies.ema16.params     import get_default_params
from strategies.ema16.indicators import populate_indicators
from strategies.ema16.logic      import generate_entries, generate_exits

def get_entries_exits(df: pd.DataFrame, params: dict = None):
    p = {**get_default_params(), **(params or {})}

    df = populate_indicators(df, p)v
    df = generate_entries(df, p)
    df = generate_exits(df, p)

    # Pass trailing params to engine via DataFrame attrs
    df.attrs["trail_trigger"] = p["trail_trigger"]
    df.attrs["trail_offset"]  = p["trail_offset"]

    # Warmup
    warmup = p["ema_period"] * 2
    df     = df.iloc[warmup:].copy()

    long_entries  = df["signal"] == 1
    short_entries = pd.Series(False, index=df.index)  # long only
    long_exits    = df["signal"] == -1
    short_exits   = pd.Series(False, index=df.index)

    return long_entries, short_entries, short_exits, long_exits, df

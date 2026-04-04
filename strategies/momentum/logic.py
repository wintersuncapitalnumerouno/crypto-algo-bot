import numpy as np
import pandas as pd

def generate_entries(df, params):
    df = df.copy()
    trend      = np.where(df["ema_fast"] > df["ema_slow"], 1, -1)
    prev_trend = pd.Series(trend, index=df.index).shift(1)
    cross_up   = (trend == 1)  & (prev_trend == -1)
    cross_down = (trend == -1) & (prev_trend == 1)
    adx_ok     = df["adx"] >= params["adx_min"]
    htf_up     = df["close"] > df["htf_ema"]
    htf_down   = df["close"] < df["htf_ema"]
    df["signal"] = 0
    df.loc[cross_up   & adx_ok & htf_up,   "signal"] =  1
    df.loc[cross_down & adx_ok & htf_down, "signal"] = -1
    return df

def generate_exits(df, params):
    df = df.copy()
    stop_dist = df["atr"] * params["atr_multiplier"]
    tp_dist   = stop_dist * params["rr_ratio"]
    df["stop_loss_long"]    = df["close"] - stop_dist
    df["take_profit_long"]  = df["close"] + tp_dist
    df["stop_loss_short"]   = df["close"] + stop_dist
    df["take_profit_short"] = df["close"] - tp_dist
    return df

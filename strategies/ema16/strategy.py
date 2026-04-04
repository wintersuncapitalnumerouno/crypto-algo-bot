import pandas as pd
import numpy as np
from strategies.ema16.params import get_default_params

def get_entries_exits(df: pd.DataFrame, params: dict = None):
    p = {**get_default_params(), **(params or {})}

    df = df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    df = df.copy()
    df["ema16"] = df["close"].ewm(span=p["ema_period"], adjust=False).mean()
    prev_close = df["close"].shift(1)
    prev_ema   = df["ema16"].shift(1)
    cross_above = (df["close"] > df["ema16"]) & (prev_close <= prev_ema)
    cross_below = (df["close"] < df["ema16"]) & (prev_close >= prev_ema)
    df["signal"] = 0
    df.loc[cross_above, "signal"] =  1
    df.loc[cross_below, "signal"] = -1

    # Diagnostic aliases — engine looks for ema_fast/ema_slow columns
    df["ema_fast"] = df["ema16"]
    df["ema_slow"] = df["ema16"]

    # ── ATR stop columns ──────────────────────────────────────
    # Written only when atr_stop_mult is present in params.
    # Engine reads these for stop placement.
    # Engine uses them for sizing only if use_atr_sizing=True.
    if p.get("atr_stop_mult"):
        _atr_period = p.get("atr_period", 14)
        _atr_mult   = p["atr_stop_mult"]
        _hl  = df["high"] - df["low"]
        _hc  = (df["high"] - df["close"].shift(1)).abs()
        _lc  = (df["low"]  - df["close"].shift(1)).abs()
        _tr  = pd.concat([_hl, _hc, _lc], axis=1).max(axis=1)
        _atr = _tr.ewm(span=_atr_period, adjust=False).mean()
        df["stop_loss_long"]  = df["close"] - _atr * _atr_mult
        df["stop_loss_short"] = df["close"] + _atr * _atr_mult

    df.attrs["use_atr_sizing"]      = p.get("use_atr_sizing", False)
    df.attrs["trail_trigger"]       = p["trail_trigger"]
    df.attrs["trail_offset"]        = p["trail_offset"]
    df.attrs["trail_tight_trigger"] = p.get("trail_tight_trigger", None)
    df.attrs["trail_tight_offset"]  = p.get("trail_tight_offset",  None)

    # Scaled exits — driven by params, not hardcoded here
    # Set tp_levels in params file to enable; omit to use legacy single exit
    # Format: [(price_move_pct, fraction_of_position), ...]  weights must sum to 1.0
    if p.get("tp_levels"):
        df.attrs["tp_levels"] = p["tp_levels"]

    warmup = p["ema_period"] * 2
    df     = df.iloc[warmup:].copy()
    long_entries  = df["signal"] == 1
    short_entries = pd.Series(False, index=df.index)
    long_exits    = df["signal"] == -1
    short_exits   = pd.Series(False, index=df.index)
    return long_entries, short_entries, short_exits, long_exits, df

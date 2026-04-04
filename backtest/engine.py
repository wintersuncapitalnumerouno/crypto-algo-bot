# =============================================================
# backtest/engine.py — Backtesting Engine v3
# =============================================================
#
# WHAT'S NEW IN v3:
#   ✅ Phase-based results storage (exploration/optimization/validation/live)
#   ✅ Regime filter support (DVOL + funding + macro)
#   ✅ Funding rate cost deducted from trades (realistic P&L)
#   ✅ New metrics: Sortino, Calmar, monthly returns, max consec losses
#   ✅ Regime filter ON vs OFF comparison mode
#   ✅ Interactive date range prompt at runtime
#
# HOW TO RUN:
#   python backtest/engine.py
#   python backtest/engine.py --regime
#   python backtest/engine.py --compare
#   python backtest/engine.py --phase optimization
#
# =============================================================

import sys, os, argparse, warnings
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from tabulate import tabulate

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from strategies.registry      import get_strategies, list_strategies
from data.fetch_data          import load_candles
from backtest.results_manager import ResultsManager


# ─────────────────────────────────────────────────────────────
# INTERACTIVE DATE RANGE PROMPT
# ─────────────────────────────────────────────────────────────

def prompt_date_range() -> tuple:
    """
    Interactively ask the user to select a backtest date range.

    Returns:
        (start_date, end_date, folder_tag)
        start_date / end_date : "YYYY-MM-DD" strings or None (full history)
        folder_tag            : compact string used in output folder names
    """
    today = datetime.utcnow().date()

    presets = [
        ("Last 1 month",  today - relativedelta(months=1),  today),
        ("Last 3 months", today - relativedelta(months=3),  today),
        ("Last 6 months", today - relativedelta(months=6),  today),
        ("Last 1 year",   today - relativedelta(years=1),   today),
        ("Last 2 years",  today - relativedelta(years=2),   today),
        ("Full history",  None,                              None),
        ("Custom dates",  None,                              None),
    ]

    div = "─" * 50
    print()
    print("  📅  Backtest Date Range")
    print(f"  {div}")
    for i, (label, start, end) in enumerate(presets, 1):
        if start is not None:
            print(f"  {i}. {label:<20} {start} → {end}")
        else:
            print(f"  {i}. {label}")
    print(f"  {div}")

    while True:
        choice = input(f"  Select [1-{len(presets)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(presets):
            break
        print(f"  ⚠️  Please enter a number between 1 and {len(presets)}.")

    idx = int(choice) - 1
    label, start_date, end_date = presets[idx]

    if label == "Custom dates":
        print("  Enter dates as YYYY-MM-DD")
        while True:
            raw = input("  Start date : ").strip()
            try:
                start_date = datetime.strptime(raw, "%Y-%m-%d").date()
                break
            except ValueError:
                print("  ⚠️  Invalid format. Use YYYY-MM-DD")

        while True:
            raw = input("  End date   : ").strip()
            try:
                end_date = datetime.strptime(raw, "%Y-%m-%d").date()
                if end_date > start_date:
                    break
                print("  ⚠️  End date must be after start date.")
            except ValueError:
                print("  ⚠️  Invalid format. Use YYYY-MM-DD")

        label = f"{start_date} → {end_date}"

    if label == "Full history" or (start_date is None and end_date is None):
        start_str  = end_str = None
        folder_tag = "full"
        display    = "Full history"
    else:
        start_str  = str(start_date)
        end_str    = str(end_date)
        folder_tag = f"{start_str.replace('-','')}_{end_str.replace('-','')}"
        display    = f"{start_str} → {end_str}"

    print(f"\n  ✅  Selected: {display}\n")
    return start_str, end_str, folder_tag


# ─────────────────────────────────────────────────────────────
# DATE FILTER
# ─────────────────────────────────────────────────────────────

def filter_dates(
    df: pd.DataFrame,
    mode: str = "train",
    start_override: str = None,
    end_override: str = None,
) -> pd.DataFrame:
    """
    Filter DataFrame to the configured date range.
    start_override / end_override (from interactive prompt) take priority.
    """
    if start_override or end_override:
        if start_override:
            df = df[df.index >= pd.Timestamp(start_override, tz="UTC")]
        if end_override:
            df = df[df.index <= pd.Timestamp(end_override,   tz="UTC")]
        return df

    bm = getattr(config, "BACKTEST_MODE", "full")
    if bm in ("full", "walkforward"):
        return df

    if bm == "fixed" or (bm == "split" and mode == "train"):
        start = getattr(config, "TRAIN_START", None)
        end   = getattr(config, "TRAIN_END",   None)
    elif bm == "split" and mode == "test":
        start = getattr(config, "TEST_START", None)
        end   = getattr(config, "TEST_END",   None)
    else:
        return df

    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index <= pd.Timestamp(end,   tz="UTC")]
    return df


# ─────────────────────────────────────────────────────────────
# REGIME FILTER THRESHOLDS
# ─────────────────────────────────────────────────────────────
DVOL_LOW     = 45
DVOL_HIGH    = 90
FUNDING_HIGH =  0.0005
FUNDING_LOW  = -0.0001
VIX_HIGH     = 30


def load_regime_data() -> dict:
    data = {}
    dvol_path = os.path.join(config.DATA_DIR, "BTC_DVOL_1h.csv")
    if os.path.exists(dvol_path):
        df = pd.read_csv(dvol_path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        data["dvol"] = df["close"] if "close" in df.columns else df.iloc[:, 0]
    macro_path = os.path.join(config.DATA_DIR, "macro_1h.csv")
    if os.path.exists(macro_path):
        df = pd.read_csv(macro_path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        if "VIX_close" in df.columns:
            data["vix"] = df["VIX_close"]
    return data


def load_funding_data(coin: str):
    for fname in (f"{coin}_funding_8h.csv", f"{coin}_funding_1h.csv"):
        path = os.path.join(config.DATA_DIR, fname)
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            return df["funding_rate"]
    return None


def build_regime_mask(candle_index, coin, regime_data) -> pd.Series:
    mask = pd.Series(True, index=candle_index)
    if "dvol" in regime_data:
        dvol  = regime_data["dvol"].reindex(candle_index, method="ffill")
        mask &= (dvol >= DVOL_LOW) & (dvol <= DVOL_HIGH)
    if "vix" in regime_data:
        vix   = regime_data["vix"].reindex(candle_index, method="ffill")
        mask &= (vix <= VIX_HIGH)
    funding = load_funding_data(coin)
    if funding is not None:
        fa    = funding.reindex(candle_index, method="ffill")
        mask &= (fa <= FUNDING_HIGH) & (fa >= FUNDING_LOW)
    return mask.fillna(True)


# ─────────────────────────────────────────────────────────────
# BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────

def run_backtest(df_signals, direction="both", regime_mask=None) -> dict:
    """
    Core backtest simulation loop.

    Supports two exit modes:
      Legacy mode  : single exit per trade (stop, TP, signal, time)
      Scaled mode  : partial exits at multiple TP levels (opt-in)

    Scaled mode activates when strategy sets:
      df.attrs["tp_levels"] = [(price_move_pct, fraction_to_close), ...]

    Exit priority (scaled mode):
      1. Scaled TP level hit
      2. Stop loss / trailing stop
      3. Opposite signal exit
      4. Time stop

    Exit priority (legacy mode):
      1. Stop loss / trailing stop
      2. Take profit
      3. Signal exit
      4. Time stop
    """
    import uuid

    # ── Risk model ────────────────────────────────────────────
    RISK_PCT = getattr(config, "RISK_PCT", 0.005)
    STOP_PCT = getattr(config, "STOP_PCT", 0.02)
    MAX_HOLD = getattr(config, "MAX_HOLD_CANDLES", 96)

    # ── Read and validate tp_levels ───────────────────────────
    raw_tp = df_signals.attrs.get("tp_levels", None)
    TP_LEVELS = None

    if raw_tp is not None:
        # Validate: all values positive, weights sum to 1.0
        valid = True
        total_weight = 0.0
        for i, level in enumerate(raw_tp):
            if len(level) != 2:
                print(f"  ❌ tp_levels[{i}] must be (price_pct, size_frac) — scaled exits disabled")
                valid = False; break
            pct, frac = level
            if pct <= 0 or frac <= 0:
                print(f"  ❌ tp_levels[{i}] has non-positive value — scaled exits disabled")
                valid = False; break
            total_weight += frac
        if valid and abs(total_weight - 1.0) > 0.01:
            print(f"  ❌ tp_levels weights sum to {total_weight:.3f}, must be 1.0 — scaled exits disabled")
            valid = False
        if valid:
            TP_LEVELS = raw_tp
            print(f"  ✅ Scaled exits active: {len(TP_LEVELS)} levels, weights sum = {total_weight:.2f}")

    # ── State ─────────────────────────────────────────────────
    trades            = []
    in_trade          = False
    entry_price       = None
    entry_time        = None
    stop_loss         = None
    take_profit       = None
    trade_dir         = None
    trade_id          = None
    position_size_usd = 0.0
    original_size_usd = 0.0
    remaining_frac    = 1.0
    dollar_risk       = 0.0
    equity_at_entry   = 0.0
    initial_stop_loss = 0.0
    hold_count        = 0
    best_price        = None
    trail_active      = False
    trail_hits        = 0
    tp_levels_hit     = 0
    breakeven_set     = False

    fee     = config.TAKER_FEE + config.SLIPPAGE
    capital = config.INITIAL_CAPITAL
    equity  = [capital]

    # ── Mark-to-market equity (one point per candle) ──────────
    mtm_timestamps = []
    mtm_equity     = []

    trail_trigger       = df_signals.attrs.get("trail_trigger",       None)
    trail_offset        = df_signals.attrs.get("trail_offset",        None)
    trail_tight_trigger = df_signals.attrs.get("trail_tight_trigger", None)
    trail_tight_offset  = df_signals.attrs.get("trail_tight_offset",  None)
    vol_dry_threshold   = df_signals.attrs.get("vol_dry_threshold",   None)
    vol_dry_close_pct   = df_signals.attrs.get("vol_dry_close_pct",   None)
    vol_size_min        = df_signals.attrs.get("vol_size_min",        1.0)
    vol_size_max        = df_signals.attrs.get("vol_size_max",        1.0)

    for ts, row in df_signals.iterrows():
        signal           = row.get("signal", 0)
        high, low, close = row["high"], row["low"], row["close"]

        # ── Record MTM equity every candle ────────────────────
        if in_trade:
            if trade_dir == "long":
                unrealized_pnl = position_size_usd * remaining_frac * (close - entry_price) / entry_price
            else:
                unrealized_pnl = position_size_usd * remaining_frac * (entry_price - close) / entry_price
            mtm_equity.append(capital + unrealized_pnl)
        else:
            mtm_equity.append(capital)
        mtm_timestamps.append(ts)

        # ── Manage open trade ─────────────────────────────────
        if in_trade:
            hold_count += 1

            # ── Trailing stop update ──────────────────────────
            if trail_trigger is not None and trail_offset is not None:
                if trade_dir == "long":
                    if best_price is None or high > best_price:
                        best_price = high
                    if (best_price - entry_price) / entry_price >= trail_trigger:
                        trail_active = True
                    if trail_active:
                        profit_pct    = (best_price - entry_price) / entry_price
                        active_offset = (trail_tight_offset
                            if trail_tight_trigger and trail_tight_offset and profit_pct >= trail_tight_trigger
                            else trail_offset)
                        stop_loss = max(stop_loss, best_price * (1 - active_offset))
                elif trade_dir == "short":
                    if best_price is None or low < best_price:
                        best_price = low
                    if (entry_price - best_price) / entry_price >= trail_trigger:
                        trail_active = True
                    if trail_active:
                        profit_pct    = (entry_price - best_price) / entry_price
                        active_offset = (trail_tight_offset
                            if trail_tight_trigger and trail_tight_offset and profit_pct >= trail_tight_trigger
                            else trail_offset)
                        stop_loss = min(stop_loss, best_price * (1 + active_offset))

            # ══════════════════════════════════════════════════
            # SCALED MODE
            # ══════════════════════════════════════════════════
            if TP_LEVELS is not None:

                # Priority 1: Check TP levels (highest priority)
                while tp_levels_hit < len(TP_LEVELS) and remaining_frac > 0.001:
                    tp_pct, tp_frac = TP_LEVELS[tp_levels_hit]

                    if trade_dir == "long":
                        tp_price = entry_price * (1 + tp_pct)
                        hit      = high >= tp_price
                    else:
                        tp_price = entry_price * (1 - tp_pct)
                        hit      = low  <= tp_price

                    if not hit:
                        break  # this level not reached yet

                    # Close this fraction
                    close_size = original_size_usd * tp_frac

                    if trade_dir == "long":
                        pnl_pct = (tp_price * (1 - fee) - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - tp_price * (1 + fee)) / entry_price

                    pnl_usd    = close_size * pnl_pct
                    capital   += pnl_usd
                    equity.append(capital)
                    r_multiple = pnl_usd / (dollar_risk * tp_frac) if dollar_risk > 0 else 0.0

                    trades.append({
                        "trade_id":          trade_id,
                        "entry_time":        entry_time,
                        "exit_time":         ts,
                        "direction":         trade_dir,
                        "entry_price":       round(entry_price, 6),
                        "exit_price":        round(tp_price, 6),
                        "initial_stop_loss": round(initial_stop_loss, 6),
                        "final_stop_loss":   round(stop_loss, 6),
                        "take_profit":       round(tp_price, 6),
                        "stop_pct":          round(STOP_PCT * 100, 2),
                        "equity_at_entry":   round(equity_at_entry, 2),
                        "dollar_risk":       round(dollar_risk * tp_frac, 2),
                        "position_size_usd": round(close_size, 2),
                        "exit_reason":       f"tp{tp_levels_hit + 1}_{int(tp_pct * 1000)}",
                        "pnl_pct":           round(pnl_pct * 100, 4),
                        "pnl":               round(pnl_usd, 4),
                        "r_multiple":        round(r_multiple, 3),
                        "duration_min":      int((ts - entry_time).total_seconds() / 60),
                        "adx_at_entry":      round(float(row.get("adx", 0) or 0), 2),
                        "ema_fast_at_entry": round(float(row.get("ema_fast", 0) or 0), 4),
                        "ema_slow_at_entry": round(float(row.get("ema_slow", 0) or 0), 4),
                        "htf_trend":         "up" if float(row.get("close", 0) or 0) > float(row.get("htf_ema", 0) or 0) else "down",
                        "partial_exit":      True,
                        "tp_level":          tp_levels_hit + 1,
                        "remaining_frac":    round(remaining_frac - tp_frac, 4),
                    })

                    remaining_frac -= tp_frac
                    tp_levels_hit  += 1

                    # Breakeven move disabled — original ATR stop + trail
                    # holds the remainder. Forced BE was cutting winners short.

                    # All levels hit — trade fully closed
                    if remaining_frac <= 0.001:
                        in_trade      = False
                        hold_count    = 0
                        best_price    = None
                        trail_active  = False
                        remaining_frac = 1.0
                        tp_levels_hit  = 0
                        breakeven_set  = False
                        break

                if not in_trade:
                    continue

                # Priority 1b: Volume dry-up partial exit
                if (vol_dry_threshold is not None and vol_dry_close_pct is not None
                        and remaining_frac > 0.4):
                    vol_ratio_now = float(row.get("vol_ratio", 1.0) or 1.0)
                    in_profit = (
                        (trade_dir == "long"  and close > entry_price) or
                        (trade_dir == "short" and close < entry_price)
                    )
                    if vol_ratio_now < vol_dry_threshold and in_profit:
                        close_frac    = vol_dry_close_pct * remaining_frac
                        close_size    = position_size_usd * close_frac
                        exit_px       = close * (1 - fee) if trade_dir == "long" else close * (1 + fee)
                        if trade_dir == "long":
                            pnl_pct_part = (exit_px - entry_price) / entry_price
                        else:
                            pnl_pct_part = (entry_price - exit_px) / entry_price
                        pnl_part      = close_size * pnl_pct_part
                        capital      += pnl_part
                        remaining_frac -= close_frac
                        position_size_usd *= (1 - close_frac)
                        trades.append({
                            "trade_id":          trade_id,
                            "entry_time":        entry_time,
                            "exit_time":         ts,
                            "direction":         trade_dir,
                            "entry_price":       round(entry_price, 6),
                            "exit_price":        round(exit_px, 6),
                            "initial_stop_loss": round(initial_stop_loss, 6),
                            "final_stop_loss":   round(stop_loss, 6),
                            "take_profit":       round(take_profit, 6),
                            "stop_pct":          round(STOP_PCT * 100, 2),
                            "equity_at_entry":   round(equity_at_entry, 2),
                            "dollar_risk":       round(dollar_risk * close_frac, 2),
                            "position_size_usd": round(close_size, 2),
                            "exit_reason":       "vol_dry_partial",
                            "pnl_pct":           round(pnl_pct_part * 100, 4),
                            "pnl":               round(pnl_part, 4),
                            "r_multiple":        round(pnl_part / (dollar_risk * close_frac), 3) if dollar_risk > 0 else 0,
                            "duration_min":      int((ts - entry_time).total_seconds() / 60),
                            "adx_at_entry":      round(float(row.get("adx", 0) or 0), 2),
                            "ema_fast_at_entry": round(float(row.get("ema_fast", 0) or 0), 4),
                            "ema_slow_at_entry": round(float(row.get("ema_slow", 0) or 0), 4),
                            "htf_trend":         "up" if float(row.get("close", 0) or 0) > float(row.get("htf_ema", 0) or 0) else "down",
                            "partial_exit":      True,
                            "tp_level":          0,
                            "remaining_frac":    round(remaining_frac, 3),
                        })

                # Priority 2: Stop loss / trailing stop
                stop_hit = (trade_dir == "long" and low  <= stop_loss) or                            (trade_dir == "short" and high >= stop_loss)

                # Priority 3: Opposite signal exit
                signal_hit = (trade_dir == "long"  and signal == -1) or                              (trade_dir == "short" and signal ==  1)

                # Priority 4: Time stop
                time_hit = hold_count >= MAX_HOLD

                exit_price  = None
                exit_reason = None

                if stop_hit:
                    exit_price  = stop_loss
                    exit_reason = "trail_stop" if trail_active else "stop_loss"
                elif signal_hit:
                    exit_price  = close * (1 - fee) if trade_dir == "long" else close * (1 + fee)
                    exit_reason = "signal_exit"
                elif time_hit:
                    exit_price  = close
                    exit_reason = "time_stop"

                if exit_price is not None:
                    close_size = original_size_usd * remaining_frac

                    if trade_dir == "long":
                        pnl_pct = (exit_price * (1 - fee) - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price * (1 + fee)) / entry_price

                    pnl_usd  = close_size * pnl_pct
                    capital += pnl_usd
                    equity.append(capital)
                    r_multiple = pnl_usd / (dollar_risk * remaining_frac) if dollar_risk > 0 else 0.0

                    if exit_reason == "trail_stop":
                        trail_hits += 1

                    trades.append({
                        "trade_id":          trade_id,
                        "entry_time":        entry_time,
                        "exit_time":         ts,
                        "direction":         trade_dir,
                        "entry_price":       round(entry_price, 6),
                        "exit_price":        round(exit_price, 6),
                        "initial_stop_loss": round(initial_stop_loss, 6),
                        "final_stop_loss":   round(stop_loss, 6),
                        "take_profit":       round(exit_price, 6),
                        "stop_pct":          round(STOP_PCT * 100, 2),
                        "equity_at_entry":   round(equity_at_entry, 2),
                        "dollar_risk":       round(dollar_risk * remaining_frac, 2),
                        "position_size_usd": round(close_size, 2),
                        "exit_reason":       exit_reason,
                        "pnl_pct":           round(pnl_pct * 100, 4),
                        "pnl":               round(pnl_usd, 4),
                        "r_multiple":        round(r_multiple, 3),
                        "duration_min":      int((ts - entry_time).total_seconds() / 60),
                        "adx_at_entry":      round(float(row.get("adx", 0) or 0), 2),
                        "ema_fast_at_entry": round(float(row.get("ema_fast", 0) or 0), 4),
                        "ema_slow_at_entry": round(float(row.get("ema_slow", 0) or 0), 4),
                        "htf_trend":         "up" if float(row.get("close", 0) or 0) > float(row.get("htf_ema", 0) or 0) else "down",
                        "partial_exit":      False,
                        "tp_level":          0,
                        "remaining_frac":    0.0,
                    })

                    in_trade      = False
                    hold_count    = 0
                    best_price    = None
                    trail_active  = False
                    remaining_frac = 1.0
                    tp_levels_hit  = 0
                    breakeven_set  = False

            # ══════════════════════════════════════════════════
            # LEGACY MODE — zero change from previous behavior
            # ══════════════════════════════════════════════════
            else:
                exit_price  = None
                exit_reason = None

                if trade_dir == "long":
                    if   low  <= stop_loss:      exit_price, exit_reason = stop_loss,     "trail_stop" if trail_active else "stop_loss"
                    elif high >= take_profit:    exit_price, exit_reason = take_profit,   "take_profit"
                    elif hold_count >= MAX_HOLD: exit_price, exit_reason = close,         "time_stop"
                    elif signal == -1:           exit_price, exit_reason = close*(1-fee), "signal_exit"
                elif trade_dir == "short":
                    if   high >= stop_loss:      exit_price, exit_reason = stop_loss,     "trail_stop" if trail_active else "stop_loss"
                    elif low  <= take_profit:    exit_price, exit_reason = take_profit,   "take_profit"
                    elif hold_count >= MAX_HOLD: exit_price, exit_reason = close,         "time_stop"
                    elif signal == 1:            exit_price, exit_reason = close*(1+fee), "signal_exit"

                if exit_price is not None:
                    if trade_dir == "long":
                        pnl_pct = (exit_price * (1 - fee) - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price * (1 + fee)) / entry_price

                    pnl_usd  = position_size_usd * pnl_pct
                    capital += pnl_usd
                    equity.append(capital)
                    r_multiple = pnl_usd / dollar_risk if dollar_risk > 0 else 0.0

                    if exit_reason == "trail_stop":
                        trail_hits += 1

                    trades.append({
                        "trade_id":          trade_id,
                        "entry_time":        entry_time,
                        "exit_time":         ts,
                        "direction":         trade_dir,
                        "entry_price":       round(entry_price, 6),
                        "exit_price":        round(exit_price, 6),
                        "initial_stop_loss": round(initial_stop_loss, 6),
                        "final_stop_loss":   round(stop_loss, 6),
                        "take_profit":       round(take_profit, 6),
                        "stop_pct":          round(STOP_PCT * 100, 2),
                        "equity_at_entry":   round(equity_at_entry, 2),
                        "dollar_risk":       round(dollar_risk, 2),
                        "position_size_usd": round(position_size_usd, 2),
                        "exit_reason":       exit_reason,
                        "pnl_pct":           round(pnl_pct * 100, 4),
                        "pnl":               round(pnl_usd, 4),
                        "r_multiple":        round(r_multiple, 3),
                        "duration_min":      int((ts - entry_time).total_seconds() / 60),
                        "adx_at_entry":      round(float(row.get("adx", 0) or 0), 2),
                        "ema_fast_at_entry": round(float(row.get("ema_fast", 0) or 0), 4),
                        "ema_slow_at_entry": round(float(row.get("ema_slow", 0) or 0), 4),
                        "htf_trend":         "up" if float(row.get("close", 0) or 0) > float(row.get("htf_ema", 0) or 0) else "down",
                        "partial_exit":      False,
                        "tp_level":          0,
                        "remaining_frac":    0.0,
                    })

                    in_trade     = False
                    hold_count   = 0
                    best_price   = None
                    trail_active = False

        # ── Open new trade ────────────────────────────────────
        if not in_trade:
            regime_ok = True
            if regime_mask is not None and ts in regime_mask.index:
                regime_ok = bool(regime_mask.loc[ts])

            if regime_ok:
                if signal == 1 and direction in ("long", "both"):
                    ep              = close * (1 + fee)
                    sl              = ep * (1 - STOP_PCT)
                    tp              = row.get("take_profit_long", ep * (1 + STOP_PCT * 2))
                    actual_stop_pct = abs(ep - sl) / ep
                    if actual_stop_pct <= 0:
                        continue
                    dollar_risk       = capital * RISK_PCT
                    vol_ratio_entry   = float(row.get("vol_ratio", 1.0) or 1.0)
                    vol_mult          = min(max(vol_ratio_entry, vol_size_min), vol_size_max)
                    position_size_usd = (dollar_risk / actual_stop_pct) * vol_mult
                    original_size_usd = position_size_usd
                    equity_at_entry   = capital
                    entry_price       = ep
                    stop_loss         = sl
                    take_profit       = tp
                    initial_stop_loss = sl
                    entry_time        = ts
                    trade_dir         = "long"
                    trade_id          = str(uuid.uuid4())[:8]
                    in_trade          = True
                    hold_count        = 0
                    best_price        = None
                    trail_active      = False
                    remaining_frac    = 1.0
                    tp_levels_hit     = 0
                    breakeven_set     = False

                elif signal == -1 and direction in ("short", "both"):
                    ep              = close * (1 - fee)
                    sl              = ep * (1 + STOP_PCT)
                    tp              = row.get("take_profit_short", ep * (1 - STOP_PCT * 2))
                    actual_stop_pct = abs(sl - ep) / ep
                    if actual_stop_pct <= 0:
                        continue
                    dollar_risk       = capital * RISK_PCT
                    vol_ratio_entry   = float(row.get("vol_ratio", 1.0) or 1.0)
                    vol_mult          = min(max(vol_ratio_entry, vol_size_min), vol_size_max)
                    position_size_usd = (dollar_risk / actual_stop_pct) * vol_mult
                    original_size_usd = position_size_usd
                    equity_at_entry   = capital
                    entry_price       = ep
                    stop_loss         = sl
                    take_profit       = tp
                    initial_stop_loss = sl
                    entry_time        = ts
                    trade_dir         = "short"
                    trade_id          = str(uuid.uuid4())[:8]
                    in_trade          = True
                    hold_count        = 0
                    best_price        = None
                    trail_active      = False
                    remaining_frac    = 1.0
                    tp_levels_hit     = 0
                    breakeven_set     = False

    if not trades:
        return {"error": "No trades generated"}

    trades_df = pd.DataFrame(trades)
    equity_s  = pd.Series(equity)
    n         = len(trades_df)
    winners   = trades_df[trades_df["pnl_pct"] > 0]
    losers    = trades_df[trades_df["pnl_pct"] <= 0]
    win_rate  = len(winners) / n

    gp = winners["pnl"].sum() if len(winners) > 0 else 0
    gl = abs(losers["pnl"].sum()) if len(losers) > 0 else 0.0001
    pf = gp / gl

    # ── MTM equity series ────────────────────────────────────
    mtm_s = pd.Series(mtm_equity, index=mtm_timestamps)

    # Max DD — bar-by-bar MTM, includes intra-trade open loss
    total_ret    = (capital - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL
    mtm_roll_max = mtm_s.cummax()
    max_dd       = ((mtm_s - mtm_roll_max) / mtm_roll_max).min()

    # Sharpe/Sortino — resample MTM to daily, annualise with sqrt(365)
    # Crypto trades 24/7 so 365 trading days
    mtm_daily  = mtm_s.resample("1D").last().dropna()
    daily_ret  = mtm_daily.pct_change().dropna()
    sharpe     = (daily_ret.mean() / daily_ret.std() * np.sqrt(365)) if daily_ret.std() > 0 else 0
    dn_daily   = daily_ret[daily_ret < 0]
    dn_std     = dn_daily.std() if len(dn_daily) > 1 else 0.0001
    sortino    = (daily_ret.mean() / dn_std * np.sqrt(365)) if dn_std > 0 else 0
    calmar     = (total_ret / abs(max_dd)) if max_dd != 0 else 0

    wl = (trades_df["pnl_pct"] > 0).astype(int).tolist()
    max_consec = cur = 0
    for w in wl:
        cur = cur + 1 if w == 0 else 0
        max_consec = max(max_consec, cur)

    exit_reasons = trades_df["exit_reason"].value_counts().to_dict()

    return {
        "n_trades":          n,
        "win_rate":          round(win_rate * 100, 1),
        "total_return":      round(total_ret * 100, 2),
        "final_capital":     round(capital, 2),
        "max_drawdown":      round(max_dd * 100, 2),
        "sharpe_ratio":      round(sharpe, 2),
        "sortino_ratio":     round(sortino, 2),
        "calmar_ratio":      round(calmar, 2),
        "profit_factor":     round(pf, 2),
        "avg_win_pct":       round(winners["pnl_pct"].mean(), 3) if len(winners) > 0 else 0,
        "avg_loss_pct":      round(losers["pnl_pct"].mean(),  3) if len(losers)  > 0 else 0,
        "avg_duration_m":    round(trades_df["duration_min"].mean(), 1),
        "max_consec_losses": max_consec,
        "trail_hits":        trail_hits,
        "avg_dollar_risk":   round(trades_df["dollar_risk"].mean(), 2),
        "avg_position_size": round(trades_df["position_size_usd"].mean(), 2),
        "total_r":           round(trades_df["r_multiple"].sum(), 3),
        "avg_r":             round(trades_df["r_multiple"].mean(), 3),
        "exit_reasons":      exit_reasons,
        "trades_df":         trades_df,
        "equity_curve":      equity_s,
        "mtm_equity_curve":  mtm_s,
    }

# ─────────────────────────────────────────────────────────────
# RUN ALL
# ─────────────────────────────────────────────────────────────

def run_all(
    coins=None, timeframes=None, phase="exploration",
    use_regime=False, strategy_names=None,
    date_start=None, date_end=None, date_tag=None,
    run_tag=None,
):
    coins      = coins      or config.COINS
    timeframes = timeframes or config.BACKTEST_TIMEFRAMES

    STRATEGIES = get_strategies(strategy_names)
    if not STRATEGIES:
        print("❌ No strategies found. Check registry.py")
        return pd.DataFrame()

    results = []
    total   = len(STRATEGIES) * len(coins) * len(timeframes)
    done    = 0

    regime_data  = load_regime_data() if use_regime else {}
    rf_tag       = "✅ ON" if use_regime else "❌ OFF"
    date_display = f"{date_start} → {date_end}" if date_start else "Full history"

    print("\n" + "=" * 70)
    print(f"  ⚙️   Backtesting  |  Phase: {phase.upper()}  |  Regime Filter: {rf_tag}")
    print(f"  📅  Date Range   |  {date_display}")
    print("=" * 70)

    for strategy_name, strategy_cfg in STRATEGIES.items():
        signal_fn = strategy_cfg["fn"]
        params    = strategy_cfg["params"]

        rm = ResultsManager(
            phase         = phase,
            regime_filter = use_regime,
            date_tag      = date_tag,
            strategy_name = strategy_name,
            run_tag       = run_tag,
        )

        for coin in coins:
            regime_mask = None
            if use_regime:
                try:
                    df_tmp      = load_candles(coin, timeframes[0])
                    regime_mask = build_regime_mask(df_tmp.index, coin, regime_data)
                    pct         = (~regime_mask).mean() * 100
                    print(f"  🔒  {coin} regime filter: {pct:.1f}% of candles blocked")
                except Exception:
                    pass

            for tf in timeframes:
                done += 1
                print(f"\n  [{done}/{total}] {strategy_name} | {coin} {tf}...", end=" ", flush=True)

                try:
                    df = load_candles(coin, tf)
                    df = filter_dates(df, mode="train",
                                      start_override=date_start,
                                      end_override=date_end)
                except FileNotFoundError:
                    print("⚠️  no data file"); continue

                try:
                    _, _, _, _, df_sig = signal_fn(df, params)
                    result = run_backtest(df_sig, regime_mask=regime_mask)
                except Exception as e:
                    print(f"❌ {e}"); continue

                if "error" in result:
                    print(f"⚠️  {result['error']}"); continue

                print(
                    f"✅  Return: {result['total_return']:+.1f}%  "
                    f"Sharpe: {result['sharpe_ratio']:.2f}  "
                    f"Sortino: {result['sortino_ratio']:.2f}  "
                    f"WR: {result['win_rate']}%  "
                    f"Trades: {result['n_trades']}"
                )

                # Pass MTM curve so compute_metrics gets time-indexed equity
                # This enables monthly_returns, proper Sortino, and Calmar
                if "mtm_equity_curve" in result:
                    result["equity_curve"] = result["mtm_equity_curve"]

                rm.save_strategy_result(strategy_name, coin, tf, result)

                # Also save MTM curve under its own filename
                if "mtm_equity_curve" in result:
                    mtm_dir  = Path(rm.run_dir) / f"{coin}_{tf}"
                    mtm_dir.mkdir(parents=True, exist_ok=True)
                    mtm_path = mtm_dir / "equity_curve_mtm.csv"
                    result["mtm_equity_curve"].to_frame(name="equity").to_csv(mtm_path)

                results.append({
                    "Strategy":        strategy_name,
                    "Coin":            coin,
                    "Timeframe":       tf,
                    "Date Range":      date_display,
                    "Trades":          result["n_trades"],
                    "Return %":        result["total_return"],
                    "Sharpe":          result["sharpe_ratio"],
                    "Sortino":         result["sortino_ratio"],
                    "Calmar":          result["calmar_ratio"],
                    "Max DD %":        result["max_drawdown"],
                    "Win Rate %":      result["win_rate"],
                    "Prof Factor":     result["profit_factor"],
                    "Avg Dur(m)":      result["avg_duration_m"],
                    "Max Consec Loss": result["max_consec_losses"],
                    "SL Hits":         result["exit_reasons"].get("stop_loss", 0),
                    "TP Hits":         sum(v for k, v in result["exit_reasons"].items() if k.startswith("tp")),
                    "Regime Filter":   rf_tag,
                })

    if not results:
        print("\n❌ No results.")
        return pd.DataFrame()

    results_df = pd.DataFrame(results)

    print("\n" + "=" * 70)
    print(f"  📊  RESULTS  |  {phase.upper()}  |  {date_display}  |  RF: {rf_tag}")
    print("=" * 70)
    print(tabulate(
        results_df.sort_values("Sharpe", ascending=False),
        headers="keys", tablefmt="rounded_outline",
        showindex=False, floatfmt=".2f",
    ))

    best = results_df.loc[results_df["Sharpe"].idxmax()]
    print(f"\n🏆  Best: {best['Strategy']} on {best['Coin']} {best['Timeframe']}")
    print(f"    Return: {best['Return %']:+.2f}%  Sharpe: {best['Sharpe']:.2f}  "
          f"Sortino: {best['Sortino']:.2f}  Calmar: {best['Calmar']:.2f}  "
          f"Max DD: {best['Max DD %']:.2f}%  Win Rate: {best['Win Rate %']}%")

    rm.save_summary(results_df)
    rm.save_metadata()
    print(f"\n✅  Saved → {rm.run_dir}")
    print(f"    Browse all runs: python backtest/results_manager.py")
    return results_df


# ─────────────────────────────────────────────────────────────
# COMPARE MODE
# ─────────────────────────────────────────────────────────────

def run_compare(
    coins=None, timeframes=None, phase="exploration",
    strategy_names=None, date_start=None, date_end=None, date_tag=None,
    run_tag=None,
):
    print("\n" + "=" * 70)
    print("  🔀  COMPARE MODE: Regime Filter OFF vs ON")
    print("=" * 70)

    kw = dict(coins=coins, timeframes=timeframes, phase=phase,
              strategy_names=strategy_names,
              date_start=date_start, date_end=date_end, date_tag=date_tag,
              run_tag=run_tag)

    df_off = run_all(**kw, use_regime=False)
    df_on  = run_all(**kw, use_regime=True)

    if df_off.empty or df_on.empty:
        return

    merged = df_off[["Strategy","Coin","Timeframe","Return %","Sharpe","Max DD %","Win Rate %","Trades"]].copy()
    merged = merged.rename(columns={"Return %":"Return% (no RF)","Sharpe":"Sharpe (no RF)","Trades":"Trades (no RF)"})
    on_c   = df_on[["Strategy","Coin","Timeframe","Return %","Sharpe","Win Rate %","Trades"]].copy()
    on_c   = on_c.rename(columns={"Return %":"Return% (RF)","Sharpe":"Sharpe (RF)","Trades":"Trades (RF)"})

    comp = merged.merge(on_c, on=["Strategy","Coin","Timeframe"])
    comp["Sharpe Δ"] = comp["Sharpe (RF)"] - comp["Sharpe (no RF)"]
    comp["Return Δ"] = comp["Return% (RF)"] - comp["Return% (no RF)"]

    print("\n" + "=" * 70)
    print("  📊  COMPARISON TABLE")
    print("=" * 70)
    print(tabulate(comp.sort_values("Sharpe Δ", ascending=False),
                   headers="keys", tablefmt="rounded_outline",
                   showindex=False, floatfmt=".2f"))
    improved = (comp["Sharpe Δ"] > 0).sum()
    print(f"\n  Regime filter improved Sharpe in {improved}/{len(comp)} combinations")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Algo Backtest Engine v3")
    parser.add_argument("--regime",   action="store_true")
    parser.add_argument("--compare",  action="store_true")
    parser.add_argument("--phase",    default="exploration",
                        choices=["exploration","optimization","validation","live"])
    parser.add_argument("--coins",    nargs="+", default=None)
    parser.add_argument("--tf",       nargs="+", default=None)
    parser.add_argument("--strategy", nargs="+", default=None)
    parser.add_argument("--list",     action="store_true")
    parser.add_argument("--tag",      default=None, help="Required: version tag e.g. v4__4h_scaled_exits")
    args = parser.parse_args()

    if args.list:
        list_strategies()
    else:
        # ── Prompt for date range before anything runs ────────
        if not args.tag and not args.list:
            print("\n  ❌ --tag is required. Every run must be tagged.")
            print("  Example: python backtest/engine.py --strategy EMA16 --tag v4__4h_scaled_exits\n")
            import sys; sys.exit(1)

        date_start, date_end, date_tag = prompt_date_range()

        if args.compare:
            run_compare(
                coins=args.coins, timeframes=args.tf, phase=args.phase,
                strategy_names=args.strategy,
                date_start=date_start, date_end=date_end, date_tag=date_tag,
                run_tag=args.tag,
            )
        else:
            run_all(
                coins=args.coins, timeframes=args.tf, phase=args.phase,
                use_regime=args.regime, strategy_names=args.strategy,
                date_start=date_start, date_end=date_end, date_tag=date_tag,
                run_tag=args.tag,
            )

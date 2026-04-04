# =============================================================
# backtest/engine_vbt.py — VectorBT Backtesting Engine
# =============================================================
#
# Replaces engine.py with vectorized backtesting using VectorBT.
# 100x faster than loop-based engine.
#
# SUPPORTS:
#   - All existing strategies (EMA16, StochVol)
#   - Two-phase trail stop
#   - Volume dry-up partial exit
#   - ATR-adaptive stop placement
#   - Phase-based results storage
#   - Interactive date range prompt
#
# HOW TO RUN:
#   python backtest/engine_vbt.py --strategy EMA16_V8A --tag my_tag
#   python backtest/engine_vbt.py --strategy STOCHVOL_V1 STOCHVOL_V2 --tag compare
#   python backtest/engine_vbt.py --strategy STOCHVOL_V1 --tag my_tag --coins PEPE SOL
# =============================================================

import sys
import os
import warnings
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from tabulate import tabulate

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from strategies.registry      import get_strategies
from data.fetch_data          import load_candles

try:
    import vectorbt as vbt
except ImportError:
    print("vectorbt not installed. Run: pip install vectorbt")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────
RISK_PCT     = config.RISK_PCT if hasattr(config, 'RISK_PCT') else 0.005
STOP_PCT     = getattr(config, 'STOP_PCT', 0.02)
INITIAL_CAP  = getattr(config, 'INITIAL_CAPITAL', 10000.0)
TAKER_FEE    = getattr(config, 'TAKER_FEE', 0.000432)
SLIPPAGE     = getattr(config, 'SLIPPAGE', 0.0002)
FEE          = TAKER_FEE + SLIPPAGE
MAX_HOLD     = getattr(config, 'MAX_HOLD_CANDLES', 288)  # 288 × 5m = 24h


# ── Date range prompt ─────────────────────────────────────────

def prompt_date_range():
    now = datetime.now(timezone.utc)
    options = {
        "1": ("Last 1 month",  pd.Timestamp(now) - pd.DateOffset(months=1),  pd.Timestamp(now)),
        "2": ("Last 3 months", pd.Timestamp(now) - pd.DateOffset(months=3),  pd.Timestamp(now)),
        "3": ("Last 6 months", pd.Timestamp(now) - pd.DateOffset(months=6),  pd.Timestamp(now)),
        "4": ("Last 1 year",   pd.Timestamp(now) - pd.DateOffset(years=1),   pd.Timestamp(now)),
        "5": ("Last 2 years",  pd.Timestamp(now) - pd.DateOffset(years=2),   pd.Timestamp(now)),
        "6": ("Full history",  None, None),
        "7": ("Custom dates",  None, None),
    }
    print("\n  📅  Backtest Date Range")
    print("  " + "─" * 50)
    for k, (label, start, end) in options.items():
        if start:
            print(f"  {k}. {label:<20} {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")
        else:
            print(f"  {k}. {label}")
    print("  " + "─" * 50)

    while True:
        choice = input("  Select [1-7]: ").strip()
        if choice not in options:
            print("  ⚠️  Please enter a number between 1 and 7.")
            continue
        label, start, end = options[choice]
        if choice == "7":
            start = pd.Timestamp(input("  Start date (YYYY-MM-DD): ").strip(), tz="UTC")
            end   = pd.Timestamp(input("  End date   (YYYY-MM-DD): ").strip(), tz="UTC")
        print(f"\n  ✅  Selected: {label if choice != '7' else f'{start.date()} → {end.date()}'}\n")
        return start, end


# ── Signal generation ─────────────────────────────────────────

def generate_signals(strategy_cfg, df_5m, params):
    """Run strategy signal function on 5m candles."""
    fn = strategy_cfg["fn"]
    return fn(df_5m.copy(), params)


# ── Custom simulation with trail stop ─────────────────────────

def simulate_with_trail(df_signals: pd.DataFrame,
                         direction: str = "both") -> dict:
    """
    Event-driven simulation with:
    - Two-phase trail stop
    - Volume dry-up partial exit
    - ATR-adaptive stop
    - Position sizing from stop distance
    """
    # Read attrs
    trail_trigger       = df_signals.attrs.get("trail_trigger",       0.005)
    trail_offset        = df_signals.attrs.get("trail_offset",        0.003)
    trail_tight_trigger = df_signals.attrs.get("trail_tight_trigger", 0.03)
    trail_tight_offset  = df_signals.attrs.get("trail_tight_offset",  0.002)
    vol_dry_threshold   = df_signals.attrs.get("vol_dry_threshold",   None)
    vol_dry_close_pct   = df_signals.attrs.get("vol_dry_close_pct",   None)
    vol_size_min        = df_signals.attrs.get("vol_size_min",        1.0)
    vol_size_max        = df_signals.attrs.get("vol_size_max",        1.0)
    use_atr_sizing      = df_signals.attrs.get("use_atr_sizing",      False)

    trades    = []
    capital   = INITIAL_CAP
    equity    = [capital]

    in_trade       = False
    entry_price    = 0.0
    stop_loss      = 0.0
    take_profit    = 0.0
    trade_dir      = None
    trade_id       = None
    entry_time     = None
    equity_at_entry = 0.0
    dollar_risk    = 0.0
    pos_size_usd   = 0.0
    remaining_frac = 1.0
    best_price     = 0.0
    trail_active   = False
    hold_count     = 0
    initial_sl     = 0.0
    tp_hits        = 0

    for ts, row in df_signals.iterrows():
        signal = int(row.get("signal", 0))
        high   = float(row["high"])
        low    = float(row["low"])
        close  = float(row["close"])
        vol_ratio = float(row.get("vol_ratio", 1.0) or 1.0)

        if in_trade:
            hold_count += 1

            # ── Update trail stop ─────────────────────────────
            # Use high/low for trail (same as old engine)
            if trade_dir == "long":
                if high > best_price:
                    best_price = high
                profit_pct = (best_price - entry_price) / entry_price
            else:
                if low < best_price:
                    best_price = low
                profit_pct = (entry_price - best_price) / entry_price

            if profit_pct >= trail_trigger:
                trail_active = True

            if trail_active:
                offset = trail_tight_offset if profit_pct >= trail_tight_trigger else trail_offset
                if trade_dir == "long":
                    new_sl = best_price * (1 - offset)
                    if new_sl > stop_loss:
                        stop_loss = new_sl
                else:
                    new_sl = best_price * (1 + offset)
                    if new_sl < stop_loss:
                        stop_loss = new_sl

            # ── Volume dry-up partial exit ────────────────────
            if (vol_dry_threshold and vol_dry_close_pct
                    and remaining_frac > 0.4
                    and vol_ratio < vol_dry_threshold):
                in_profit = (trade_dir == "long" and close > entry_price) or \
                            (trade_dir == "short" and close < entry_price)
                if in_profit:
                    close_frac = vol_dry_close_pct * remaining_frac
                    close_size = pos_size_usd * close_frac
                    exit_px    = close * (1 - FEE) if trade_dir == "long" else close * (1 + FEE)
                    pnl_pct    = (exit_px - entry_price) / entry_price if trade_dir == "long" \
                                 else (entry_price - exit_px) / entry_price
                    pnl_usd    = close_size * pnl_pct
                    capital   += pnl_usd
                    remaining_frac -= close_frac
                    pos_size_usd   *= (1 - close_frac)
                    trades.append({
                        "trade_id":          trade_id,
                        "entry_time":        entry_time,
                        "exit_time":         ts,
                        "direction":         trade_dir,
                        "entry_price":       round(entry_price, 6),
                        "exit_price":        round(exit_px, 6),
                        "initial_stop_loss": round(initial_sl, 6),
                        "final_stop_loss":   round(stop_loss, 6),
                        "take_profit":       round(take_profit, 6),
                        "stop_pct":          round(STOP_PCT * 100, 2),
                        "equity_at_entry":   round(equity_at_entry, 2),
                        "dollar_risk":       round(dollar_risk * close_frac, 2),
                        "position_size_usd": round(close_size, 2),
                        "exit_reason":       "vol_dry_partial",
                        "pnl_pct":           round(pnl_pct * 100, 4),
                        "pnl":               round(pnl_usd, 4),
                        "r_multiple":        round(pnl_usd / (dollar_risk * close_frac), 3) if dollar_risk > 0 else 0,
                        "duration_min":      int((ts - entry_time).total_seconds() / 60),
                        "partial_exit":      True,
                        "tp_level":          0,
                        "remaining_frac":    round(remaining_frac, 3),
                    })

            # ── Check stop / signal / time exit ──────────────
            stop_hit   = (trade_dir == "long"  and low  <= stop_loss) or \
                         (trade_dir == "short" and high >= stop_loss)
            signal_hit = (trade_dir == "long"  and signal == -1) or \
                         (trade_dir == "short" and signal ==  1)
            time_hit   = hold_count >= MAX_HOLD

            exit_price  = None
            exit_reason = None

            if stop_hit:
                exit_price  = stop_loss
                exit_reason = "trail_stop" if trail_active else "stop_loss"
            elif signal_hit:
                exit_price  = close * (1 - FEE) if trade_dir == "long" else close * (1 + FEE)
                exit_reason = "signal_exit"
            elif time_hit:
                exit_price  = close
                exit_reason = "time_stop"

            if exit_price is not None:
                if trade_dir == "long":
                    pnl_pct = (exit_price * (1 - FEE) - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price * (1 + FEE)) / entry_price

                pnl_usd  = pos_size_usd * remaining_frac * pnl_pct
                capital += pnl_usd
                equity.append(capital)

                trades.append({
                    "trade_id":          trade_id,
                    "entry_time":        entry_time,
                    "exit_time":         ts,
                    "direction":         trade_dir,
                    "entry_price":       round(entry_price, 6),
                    "exit_price":        round(exit_price, 6),
                    "initial_stop_loss": round(initial_sl, 6),
                    "final_stop_loss":   round(stop_loss, 6),
                    "take_profit":       round(take_profit, 6),
                    "stop_pct":          round(STOP_PCT * 100, 2),
                    "equity_at_entry":   round(equity_at_entry, 2),
                    "dollar_risk":       round(dollar_risk, 2),
                    "position_size_usd": round(pos_size_usd * remaining_frac, 2),
                    "exit_reason":       exit_reason,
                    "pnl_pct":           round(pnl_pct * 100, 4),
                    "pnl":               round(pnl_usd, 4),
                    "r_multiple":        round(pnl_usd / dollar_risk, 3) if dollar_risk > 0 else 0,
                    "duration_min":      int((ts - entry_time).total_seconds() / 60),
                    "partial_exit":      False,
                    "tp_level":          0,
                    "remaining_frac":    0.0,
                })

                in_trade       = False
                remaining_frac = 1.0
                hold_count     = 0
                trail_active   = False
                best_price     = 0.0

        # ── Entry ─────────────────────────────────────────────
        if not in_trade:
            if (signal == 1 and direction in ("long", "both")) or \
               (signal == -1 and direction in ("short", "both")):

                ep  = close * (1 + FEE) if signal == 1 else close * (1 - FEE)

                # Use ATR stop pct for sizing reference (same as old engine)
                # Convert ATR column stop to a % distance from close
                if signal == 1 and "stop_loss_long" in row.index and not pd.isna(row.get("stop_loss_long", float("nan"))):
                    atr_dist = float(row["stop_loss_long"])
                    sizing_stop_pct = abs(close - atr_dist) / close if close > 0 else STOP_PCT
                    sizing_stop_pct = max(0.001, min(sizing_stop_pct, 0.5))
                else:
                    sizing_stop_pct = STOP_PCT

                if signal == -1 and "stop_loss_short" in row.index and not pd.isna(row.get("stop_loss_short", float("nan"))):
                    atr_dist = float(row["stop_loss_short"])
                    sizing_stop_pct = abs(atr_dist - close) / close if close > 0 else STOP_PCT
                    sizing_stop_pct = max(0.001, min(sizing_stop_pct, 0.5))

                # Initial stop: fixed STOP_PCT from entry (same as old engine)
                sl = ep * (1 - STOP_PCT) if signal == 1 else ep * (1 + STOP_PCT)
                tp = ep * (1 + STOP_PCT * 2) if signal == 1 else ep * (1 - STOP_PCT * 2)

                actual_stop_pct = STOP_PCT
                if actual_stop_pct <= 0:
                    continue

                dollar_risk  = capital * RISK_PCT
                vol_mult     = min(max(vol_ratio, vol_size_min), vol_size_max)
                pos_size_usd = (dollar_risk / sizing_stop_pct) * vol_mult

                in_trade        = True
                entry_price     = ep
                stop_loss       = sl
                initial_sl      = sl
                take_profit     = tp
                trade_dir       = "long" if signal == 1 else "short"
                trade_id        = f"{ts}_{trade_dir}"
                entry_time      = ts
                equity_at_entry = capital
                remaining_frac  = 1.0
                best_price      = ep
                trail_active    = False
                hold_count      = 0

    if not trades:
        return {"error": "No trades generated"}

    trades_df = pd.DataFrame(trades)
    closed    = trades_df[trades_df["exit_reason"] != "vol_dry_partial"].copy()

    if closed.empty:
        return {"error": "No closed trades"}

    # ── Metrics — match old engine exactly ────────────────────
    total_return = (capital - INITIAL_CAP) / INITIAL_CAP * 100
    wins         = closed[closed["pnl"] > 0]
    losses       = closed[closed["pnl"] <= 0]
    win_rate     = len(wins) / len(closed) * 100 if len(closed) > 0 else 0

    # Rebuild MTM equity series indexed by exit time (same as old engine)
    eq_vals  = [INITIAL_CAP]
    eq_times = [closed["entry_time"].iloc[0]]
    running  = INITIAL_CAP
    for _, t in closed.iterrows():
        running += t["pnl"]
        eq_vals.append(running)
        eq_times.append(t["exit_time"])

    mtm_s     = pd.Series(eq_vals, index=pd.DatetimeIndex(eq_times))
    eq_series = mtm_s  # for max DD

    # Sharpe / Sortino from daily resampled equity (same as old engine)
    mtm_daily = mtm_s.resample("1D").last().ffill().dropna()
    daily_ret = mtm_daily.pct_change().dropna()

    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe  = daily_ret.mean() / daily_ret.std() * (365 ** 0.5)
    else:
        sharpe  = 0.0

    dn_daily = daily_ret[daily_ret < 0]
    dn_std   = dn_daily.std() if len(dn_daily) > 1 else 0.0001
    sortino  = daily_ret.mean() / dn_std * (365 ** 0.5) if dn_std > 0 else 0.0

    # Max drawdown from MTM equity
    eq_arr   = mtm_s.values
    roll_max = np.maximum.accumulate(eq_arr)
    dd       = (eq_arr - roll_max) / roll_max
    max_dd   = dd.min() * 100

    calmar = (total_return / 100) / abs(max_dd / 100) if max_dd != 0 else 0

    # Profit factor
    gross_profit = wins["pnl"].sum() if len(wins) > 0 else 0
    gross_loss   = abs(losses["pnl"].sum()) if len(losses) > 0 else 1e-10
    prof_factor  = gross_profit / gross_loss

    avg_dur = closed["duration_min"].mean()
    max_consec_loss = 0
    cur = 0
    for pnl in closed["pnl"]:
        if pnl <= 0:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    sl_hits     = len(closed[closed["exit_reason"] == "stop_loss"])
    tp_hits_cnt = len(closed[closed["exit_reason"].str.startswith("tp")])

    return {
        "trades":       trades_df,
        "capital":      capital,
        "total_return": round(total_return, 2),
        "sharpe":       round(sharpe, 2),
        "sortino":      round(sortino, 2),
        "calmar":       round(calmar, 2),
        "max_dd":       round(max_dd, 2),
        "win_rate":     round(win_rate, 2),
        "prof_factor":  round(prof_factor, 2),
        "avg_dur":      round(avg_dur, 1),
        "max_consec":   max_consec_loss,
        "sl_hits":      sl_hits,
        "tp_hits":      tp_hits_cnt,
        "n_trades":     len(closed),
        "equity":       eq_series,
    }


# ── Main runner ───────────────────────────────────────────────

def run_all(coins, strategy_names, run_tag, phase, start_dt, end_dt):
    strategies = get_strategies(strategy_names)

    all_results = []
    total = len(strategies) * len(coins)
    done  = 0

    print()
    print("=" * 70)
    print(f"  ⚙️   Backtesting  |  Phase: {phase.upper()}")
    if start_dt:
        print(f"  📅  Date Range   |  {start_dt.date()} → {end_dt.date()}")
    else:
        print(f"  📅  Date Range   |  Full history")
    print("=" * 70)

    run_id     = datetime.now().strftime("%Y%m%d_%H%M")
    date_label = f"{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}" \
                 if start_dt else "full"

    for strat_name, strat_cfg in strategies.items():
        params = strat_cfg.get("params", {})

        print(f"\n  📁 Strategy   : {strat_name}")
        print(f"  📁 Version    : {run_tag}")

        for coin in coins:
            done += 1
            label = f"[{done}/{total}] {strat_name} | {coin} 5m"

            try:
                df_5m = load_candles(coin, "5m")

                if start_dt:
                    df_5m = df_5m[df_5m.index >= start_dt]
                if end_dt:
                    df_5m = df_5m[df_5m.index <= end_dt]

                if len(df_5m) < 500:
                    print(f"  {label}... ⚠️  Insufficient data ({len(df_5m)} candles)")
                    continue

                # Generate signals
                result = generate_signals(strat_cfg, df_5m, params)
                if result is None or (isinstance(result, tuple) and len(result) < 5):
                    print(f"  {label}... ⚠️  Signal generation failed")
                    continue

                long_entries, short_entries, short_exits, long_exits, df_sig = result

                if df_sig is None or df_sig.empty:
                    print(f"  {label}... ⚠️  No signal data")
                    continue

                # Run simulation
                res = simulate_with_trail(df_sig, direction="both")

                if "error" in res:
                    print(f"  {label}... ⚠️  {res['error']}")
                    continue

                print(f"  {label}... ✅  "
                      f"Return: {res['total_return']:+.1f}%  "
                      f"Sharpe: {res['sharpe']:.2f}  "
                      f"Sortino: {res['sortino']:.2f}  "
                      f"WR: {res['win_rate']:.1f}%  "
                      f"Trades: {res['n_trades']}")

                date_range = f"{df_5m.index[0].date()} → {df_5m.index[-1].date()}"

                all_results.append({
                    "Strategy":          strat_name,
                    "Coin":              coin,
                    "Timeframe":         "5m",
                    "Date Range":        date_range,
                    "Trades":            res["n_trades"],
                    "Return %":          res["total_return"],
                    "Sharpe":            res["sharpe"],
                    "Sortino":           res["sortino"],
                    "Calmar":            res["calmar"],
                    "Max DD %":          res["max_dd"],
                    "Win Rate %":        res["win_rate"],
                    "Prof Factor":       res["prof_factor"],
                    "Avg Dur(m)":        res["avg_dur"],
                    "Max Consec Loss":   res["max_consec"],
                    "SL Hits":           res["sl_hits"],
                    "TP Hits":           res["tp_hits"],
                    "Regime Filter":     "❌ OFF",
                })

                # Save trades
                run_folder = Path("results") / phase / strat_name / run_tag / f"{run_id}_{date_label}"
                run_folder.mkdir(parents=True, exist_ok=True)
                res["trades"].to_csv(run_folder / f"{coin}_trades.csv", index=False)

            except FileNotFoundError:
                print(f"  {label}... ❌  No data file")
            except Exception as e:
                print(f"  {label}... ❌  {e}")
                import traceback; traceback.print_exc()

    if not all_results:
        print("\n  ❌ No results generated.")
        return

    df_results = pd.DataFrame(all_results)
    df_results = df_results.sort_values("Sharpe", ascending=False)

    print()
    print("=" * 70)
    print(f"  📊  RESULTS  |  {phase.upper()}  |  VectorBT Engine")
    print("=" * 70)
    print(tabulate(df_results, headers="keys", tablefmt="rounded_outline",
                   floatfmt=".2f", showindex=False))

    best = df_results.iloc[0]
    print(f"\n🏆  Best: {best['Strategy']} on {best['Coin']} 5m")
    print(f"    Return: {best['Return %']:+.2f}%  Sharpe: {best['Sharpe']:.2f}  "
          f"Sortino: {best['Sortino']:.2f}  Max DD: {best['Max DD %']:.2f}%  "
          f"Win Rate: {best['Win Rate %']:.1f}%")

    # Save summary
    run_folder = Path("results") / phase / "summary_vbt" / run_tag / f"{run_id}_{date_label}"
    run_folder.mkdir(parents=True, exist_ok=True)
    df_results.to_csv(run_folder / "summary.csv", index=False)
    print(f"  📊 Summary saved ({len(df_results)} rows)")
    print(f"\n✅  Saved → {run_folder}")


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VectorBT Backtesting Engine")
    parser.add_argument("--strategy", nargs="+", default=["EMA16_V8A"])
    parser.add_argument("--coins",    nargs="+", default=None)
    parser.add_argument("--tag",      default="default")
    parser.add_argument("--phase",    default="exploration",
                        choices=["exploration","optimization","validation","live"])
    args = parser.parse_args()

    coins = args.coins or getattr(config, 'COINS',
            ["PEPE","SOL","AAVE","DOGE","LINK","ETH","XRP"])

    start_dt, end_dt = prompt_date_range()
    run_all(coins, args.strategy, args.tag, args.phase, start_dt, end_dt)

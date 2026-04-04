# =============================================================
# backtest/walk_forward.py
# =============================================================
# Rolling walk-forward validation for StochVol strategies.
#
# Method: Anchored expanding window
#   - Train window: 12 months
#   - Test window:  3 months
#   - Step:         3 months (non-overlapping test periods)
#
# Windows (2 years of data: 2024-03-30 → 2026-03-30):
#   W1: Train 2024-03-30→2025-03-30 | Test 2025-03-30→2025-06-30
#   W2: Train 2024-03-30→2025-06-30 | Test 2025-06-30→2025-09-30
#   W3: Train 2024-03-30→2025-09-30 | Test 2025-09-30→2025-12-30
#   W4: Train 2024-03-30→2025-12-30 | Test 2025-12-30→2026-03-30
#
# Usage:
#   python backtest/walk_forward.py \
#     --strategy STOCHVOL_V1 STOCHVOL_V3 \
#     --coins PEPE SOL AAVE DOGE LINK ETH XRP
# =============================================================

import sys
import os
import warnings
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from tabulate import tabulate

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from data.fetch_data import load_candles
from strategies.registry import get_strategies
from backtest.engine import run_backtest as engine_run_backtest

# ── Walk-forward windows ──────────────────────────────────────
# Each tuple: (train_start, test_start, test_end)
# Train always starts at the same anchor point.

ANCHOR_START  = "2024-03-30"
TRAIN_MONTHS  = 12
TEST_MONTHS   = 3
N_WINDOWS     = 4


def build_windows():
    anchor = pd.Timestamp(ANCHOR_START, tz="UTC")
    windows = []
    for i in range(N_WINDOWS):
        train_start = anchor
        test_start  = anchor + relativedelta(months=TRAIN_MONTHS + i * TEST_MONTHS)
        test_end    = test_start + relativedelta(months=TEST_MONTHS)
        windows.append({
            "window":      i + 1,
            "train_start": train_start,
            "train_end":   test_start,
            "test_start":  test_start,
            "test_end":    test_end,
        })
    return windows


# ── Run backtest on a date-sliced DataFrame ───────────────────

def run_backtest_on_slice(df_signals: pd.DataFrame) -> dict:
    """Identical logic to the main engine's run_backtest."""
    trades      = []
    in_trade    = False
    entry_price = None
    entry_time  = None
    stop_loss   = None
    trade_dir   = None
    hold_count  = 0

    fee          = config.TAKER_FEE + config.SLIPPAGE
    capital      = config.INITIAL_CAPITAL
    equity       = [capital]
    MAX_HOLD     = 96  # candles (8h at 5m)

    # Trail stop state
    trail_trigger       = df_signals.attrs.get("trail_trigger",       0.005)
    trail_offset        = df_signals.attrs.get("trail_offset",        0.003)
    trail_tight_trigger = df_signals.attrs.get("trail_tight_trigger", 0.030)
    trail_tight_offset  = df_signals.attrs.get("trail_tight_offset",  0.002)
    use_atr_sizing      = df_signals.attrs.get("use_atr_sizing",      False)
    vol_size_min        = df_signals.attrs.get("vol_size_min",        1.0)
    vol_size_max        = df_signals.attrs.get("vol_size_max",        1.0)
    vol_dry_threshold   = df_signals.attrs.get("vol_dry_threshold",   None)
    vol_dry_close_pct   = df_signals.attrs.get("vol_dry_close_pct",   0.0)

    best_price      = None
    trail_active    = False
    remaining_frac  = 1.0
    position_size   = config.INITIAL_CAPITAL * config.RISK_PCT

    for ts, row in df_signals.iterrows():
        signal = int(row.get("signal", 0))
        high   = float(row["high"])
        low    = float(row["low"])
        close  = float(row["close"])
        atr    = float(row.get("atr", close * 0.01))
        vol_ratio = float(row.get("vol_ratio", 1.0) or 1.0)

        if in_trade:
            hold_count += 1
            exit_price  = None
            exit_reason = None

            # Update best price and trail activation
            if trade_dir == "long":
                if close > best_price:
                    best_price = close
                move_pct = (best_price - entry_price) / entry_price
                if move_pct >= trail_tight_trigger:
                    trail_stop = best_price * (1 - trail_tight_offset)
                elif move_pct >= trail_trigger:
                    trail_stop = best_price * (1 - trail_offset)
                    trail_active = True
                else:
                    trail_stop = stop_loss

                effective_stop = max(stop_loss, trail_stop) if trail_active else stop_loss

                if low <= effective_stop:
                    exit_price  = effective_stop
                    exit_reason = "stop_loss"
                elif hold_count >= MAX_HOLD:
                    exit_price  = close
                    exit_reason = "time_stop"
                elif signal == -1:
                    exit_price  = close * (1 - fee)
                    exit_reason = "signal_exit"

            elif trade_dir == "short":
                if close < best_price:
                    best_price = close
                move_pct = (entry_price - best_price) / entry_price
                if move_pct >= trail_tight_trigger:
                    trail_stop = best_price * (1 + trail_tight_offset)
                elif move_pct >= trail_trigger:
                    trail_stop = best_price * (1 + trail_offset)
                    trail_active = True
                else:
                    trail_stop = stop_loss

                effective_stop = min(stop_loss, trail_stop) if trail_active else stop_loss

                if high >= effective_stop:
                    exit_price  = effective_stop
                    exit_reason = "stop_loss"
                elif hold_count >= MAX_HOLD:
                    exit_price  = close
                    exit_reason = "time_stop"
                elif signal == 1:
                    exit_price  = close * (1 + fee)
                    exit_reason = "signal_exit"

            # Volume dry-up partial exit
            if exit_price is None and vol_dry_threshold is not None:
                if vol_ratio < vol_dry_threshold and remaining_frac > 0.4:
                    partial_frac = vol_dry_close_pct * remaining_frac
                    if trade_dir == "long":
                        partial_pnl = (close * (1 - fee) - entry_price) / entry_price
                    else:
                        partial_pnl = (entry_price - close * (1 + fee)) / entry_price
                    if partial_pnl > 0:
                        capital        *= (1 + partial_pnl * partial_frac)
                        remaining_frac -= partial_frac
                        equity.append(capital)

            if exit_price is not None:
                if trade_dir == "long":
                    pnl_pct = (exit_price * (1 - fee) - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price * (1 + fee)) / entry_price

                pnl_pct *= remaining_frac
                trades.append({
                    "entry_time":   entry_time,
                    "exit_time":    ts,
                    "direction":    trade_dir,
                    "entry_price":  entry_price,
                    "exit_price":   exit_price,
                    "exit_reason":  exit_reason,
                    "pnl_pct":      pnl_pct,
                    "duration_min": int((ts - entry_time).total_seconds() / 60),
                })
                capital        *= (1 + pnl_pct)
                equity.append(capital)
                in_trade        = False
                hold_count      = 0
                remaining_frac  = 1.0
                trail_active    = False

        if not in_trade:
            if signal == 1:
                sl = float(row.get("stop_loss_long", close * 0.98))
                if use_atr_sizing:
                    stop_dist = max(close - sl, close * 0.001)
                    vol_mult  = min(max(vol_ratio, vol_size_min), vol_size_max)
                    position_size = (capital * config.RISK_PCT / stop_dist) * close * vol_mult
                entry_price    = close * (1 + fee)
                entry_time     = ts
                trade_dir      = "long"
                stop_loss      = sl
                best_price     = entry_price
                in_trade       = True
                hold_count     = 0
                trail_active   = False
                remaining_frac = 1.0

            elif signal == -1:
                sl = float(row.get("stop_loss_short", close * 1.02))
                if use_atr_sizing:
                    stop_dist = max(sl - close, close * 0.001)
                    vol_mult  = min(max(vol_ratio, vol_size_min), vol_size_max)
                    position_size = (capital * config.RISK_PCT / stop_dist) * close * vol_mult
                entry_price    = close * (1 - fee)
                entry_time     = ts
                trade_dir      = "short"
                stop_loss      = sl
                best_price     = entry_price
                in_trade       = True
                hold_count     = 0
                trail_active   = False
                remaining_frac = 1.0

    if not trades:
        return None

    trades_df = pd.DataFrame(trades)
    equity_s  = pd.Series(equity)
    n         = len(trades_df)
    winners   = trades_df[trades_df["pnl_pct"] > 0]
    losers    = trades_df[trades_df["pnl_pct"] <= 0]
    win_rate  = len(winners) / n

    returns   = trades_df["pnl_pct"]
    sharpe    = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

    roll_max  = equity_s.cummax()
    drawdowns = (equity_s - roll_max) / roll_max
    max_dd    = drawdowns.min()

    total_return = (equity_s.iloc[-1] - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL

    gross_profit  = winners["pnl_pct"].sum() if len(winners) > 0 else 0
    gross_loss    = abs(losers["pnl_pct"].sum()) if len(losers) > 0 else 1e-6
    profit_factor = gross_profit / gross_loss

    return {
        "n_trades":     n,
        "win_rate":     round(win_rate * 100, 1),
        "total_return": round(total_return * 100, 2),
        "sharpe":       round(sharpe, 2),
        "max_dd":       round(max_dd * 100, 2),
        "profit_factor": round(profit_factor, 2),
    }


# ── Main walk-forward runner ──────────────────────────────────

def run_walk_forward(strategy_names, coins):
    strategies = get_strategies(strategy_names)
    windows    = build_windows()

    print("\n" + "=" * 70)
    print("  🔄  Walk-Forward Validation")
    print(f"  📅  Anchor: {ANCHOR_START} | Train: {TRAIN_MONTHS}m | Test: {TEST_MONTHS}m | Windows: {N_WINDOWS}")
    print("=" * 70)

    all_results = []

    for strat_name, strat_cfg in strategies.items():
        signal_fn = strat_cfg["fn"]
        params    = strat_cfg.get("params", {})

        for coin in coins:
            print(f"\n  {strat_name} | {coin}")
            print(f"  {'Window':<8} {'Train Period':<28} {'Test Period':<28} {'Trades':>7} {'Sharpe':>8} {'Return':>9} {'WR':>7} {'DD':>8}")
            print("  " + "─" * 100)

            try:
                df_full = load_candles(coin, "5m")
            except FileNotFoundError:
                print(f"  ⚠️  No data for {coin}")
                continue

            window_results = []

            for w in windows:
                # Slice full df for train period (strategy needs full context for warmup)
                df_train = df_full[df_full.index < w["test_start"]]
                df_test  = df_full[
                    (df_full.index >= w["test_start"]) &
                    (df_full.index <  w["test_end"])
                ]

                if len(df_train) < 500 or len(df_test) < 100:
                    print(f"  W{w['window']}      ⚠️  insufficient data")
                    continue

                try:
                    # Run signal on full train data to get warmup-corrected signals
                    _, _, _, _, df_sig_train = signal_fn(df_train, params)

                    # Now run signal on full data up to test end, then slice to test period
                    df_up_to_test_end = df_full[df_full.index < w["test_end"]]
                    _, _, _, _, df_sig_full = signal_fn(df_up_to_test_end, params)

                    # Slice to test window only
                    df_sig_test = df_sig_full[
                        (df_sig_full.index >= w["test_start"]) &
                        (df_sig_full.index <  w["test_end"])
                    ].copy()

                    # Carry attrs
                    df_sig_test.attrs = df_sig_full.attrs

                    if len(df_sig_test) < 50:
                        print(f"  W{w['window']}      ⚠️  test slice too small after warmup")
                        continue

                    result_raw = engine_run_backtest(df_sig_test)

                    if "error" in result_raw:
                        print(f"  W{w['window']}      ⚠️  no trades in test window")
                        continue

                    result = {
                        "n_trades": result_raw["n_trades"],
                        "win_rate": result_raw["win_rate"],
                        "total_return": result_raw["total_return"],
                        "sharpe": result_raw["sharpe_ratio"],
                        "max_dd": result_raw["max_drawdown"],
                        "profit_factor": result_raw["profit_factor"],
                    }

                    train_str = f"{w['train_start'].date()} → {w['train_end'].date()}"
                    test_str  = f"{w['test_start'].date()} → {w['test_end'].date()}"

                    print(f"  W{w['window']}      {train_str:<28} {test_str:<28} "
                          f"{result['n_trades']:>7} "
                          f"{result['sharpe']:>8.2f} "
                          f"{result['total_return']:>+8.1f}% "
                          f"{result['win_rate']:>6.1f}% "
                          f"{result['max_dd']:>7.2f}%")

                    window_results.append(result)
                    all_results.append({
                        "Strategy":    strat_name,
                        "Coin":        coin,
                        "Window":      f"W{w['window']}",
                        "Test Period": f"{w['test_start'].date()} → {w['test_end'].date()}",
                        "Trades":      result["n_trades"],
                        "Sharpe":      result["sharpe"],
                        "Return %":    result["total_return"],
                        "Win Rate %":  result["win_rate"],
                        "Max DD %":    result["max_dd"],
                        "Prof Factor": result["profit_factor"],
                    })

                except Exception as e:
                    print(f"  W{w['window']}      ❌ {e}")
                    continue

            # Print per-coin average across windows
            if window_results:
                avg_sharpe = np.mean([r["sharpe"] for r in window_results])
                avg_return = np.mean([r["total_return"] for r in window_results])
                avg_wr     = np.mean([r["win_rate"] for r in window_results])
                avg_dd     = np.mean([r["max_dd"] for r in window_results])
                n_positive = sum(1 for r in window_results if r["total_return"] > 0)
                print(f"  {'─'*100}")
                print(f"  {'AVG':<8} {'':28} {'':28} "
                      f"{'':>7} "
                      f"{avg_sharpe:>8.2f} "
                      f"{avg_return:>+8.1f}% "
                      f"{avg_wr:>6.1f}% "
                      f"{avg_dd:>7.2f}%  "
                      f"({n_positive}/{len(window_results)} windows profitable)")

    # ── Summary table ─────────────────────────────────────────
    if not all_results:
        print("\n❌ No results.")
        return

    df_results = pd.DataFrame(all_results)

    print("\n\n" + "=" * 70)
    print("  📊  Walk-Forward Summary — Average per Strategy/Coin")
    print("=" * 70)

    summary = df_results.groupby(["Strategy", "Coin"]).agg(
        Avg_Sharpe  = ("Sharpe",     "mean"),
        Avg_Return  = ("Return %",   "mean"),
        Avg_WR      = ("Win Rate %", "mean"),
        Avg_DD      = ("Max DD %",   "mean"),
        Profitable  = ("Return %",   lambda x: f"{(x > 0).sum()}/{len(x)}"),
    ).reset_index().sort_values("Avg_Sharpe", ascending=False)

    print(tabulate(
        summary,
        headers="keys",
        tablefmt="rounded_outline",
        showindex=False,
        floatfmt=".2f",
    ))

    # ── Save results ──────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path("results/walkforward")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"walkforward_{ts}.csv"
    df_results.to_csv(out_file, index=False)
    print(f"\n✅  Results saved → {out_file}")


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-forward validation")
    parser.add_argument("--strategy", nargs="+", required=True,
                        help="Strategy names e.g. STOCHVOL_V1 STOCHVOL_V3")
    parser.add_argument("--coins", nargs="+",
                        default=["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"])
    args = parser.parse_args()

    run_walk_forward(args.strategy, args.coins)

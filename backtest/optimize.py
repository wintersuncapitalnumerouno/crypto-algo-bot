# =============================================================
# backtest/optimize.py
# =============================================================
# Stage 2 basket optimizer for StochVol V3.
#
# Method:
#   For each walk-forward window:
#     1. Run all 27 param combos on TRAIN data (full coin basket)
#     2. Score each combo — apply hard filters, rank survivors
#     3. Freeze winner → evaluate on OOS data
#     4. Save per-window artifacts
#
# Param grid (27 combos — 3 axes, all others fixed at V3 defaults):
#   stoch_k      : 14, 21, 28
#   entry_window : 1, 2, 3
#   vol_min_ratio: 0.3, 0.5, 0.7
#
# Hard filters (combo rejected if any fail):
#   - fewer than 5/N coins with positive Sharpe  -> reject
#   - fewer than 5/N coins profitable            -> reject
#   - any coin DD worse than -25%                -> reject
#   - avg trades per coin < 3                    -> reject
#
# Survivors ranked by:
#   1. avg_sharpe   (primary)
#   2. avg_calmar   (secondary)
#   3. worst_dd     (tiebreak -- less negative = better)
#
# V3 defaults (fixed -- not varied):
#   stoch_d=5, stoch_smooth=5, atr_stop_mult=0.7
#   trail_trigger=0.005, trail_offset=0.003
#   trail_tight_trigger=0.03, trail_tight_offset=0.002
#   vol_dry_threshold=0.50, vol_dry_close_pct=0.60
#
# Usage (run from project root):
#   cd ~/Desktop/crypto-algo-bot
#   python backtest/optimize.py
#   python backtest/optimize.py --coins PEPE SOL AAVE DOGE LINK ETH XRP
#
# Outputs saved to results/optimize/:
#   train_leaderboard_W{n}.csv   -- all passing combos ranked
#   selected_params_W{n}.json    -- winning params for that window
#   oos_results_W{n}.csv         -- OOS coin-by-coin results
#   basket_summary.csv           -- one row per window, train vs OOS
# =============================================================

import sys
import json
import warnings
import argparse
import itertools
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from tabulate import tabulate

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from data.fetch_data import load_candles
from strategies.stochvol.strategy_v3 import get_entries_exits
from backtest.engine import run_backtest as engine_run_backtest

# -- Walk-forward windows (same anchor as walk_forward.py) -----

ANCHOR_START = "2024-03-30"
TRAIN_MONTHS = 12
TEST_MONTHS  = 3
N_WINDOWS    = 4

COINS_DEFAULT = ["PEPE", "SOL", "AAVE", "DOGE", "LINK", "ETH", "XRP"]

# -- V3 fixed params (not varied in this grid) -----------------

V3_FIXED = {
    "stoch_d":             5,
    "stoch_smooth":        5,
    "vol_period":         20,
    "vol_size_min":        1.0,
    "vol_size_max":        2.0,
    "atr_period":         14,
    "atr_stop_mult":       0.7,
    "trail_trigger":       0.005,
    "trail_offset":        0.003,
    "trail_tight_trigger": 0.03,
    "trail_tight_offset":  0.002,
    "vol_dry_threshold":   0.50,
    "vol_dry_close_pct":   0.60,
    "risk_pct":            0.005,
}

# -- Param grid (27 combos) ------------------------------------

STOCH_K_VALUES       = [14, 21, 28]
ENTRY_WINDOW_VALUES  = [1, 2, 3]
VOL_MIN_RATIO_VALUES = [0.3, 0.5, 0.7]


def get_param_grid():
    """Returns list of 27 param dicts (3 x 3 x 3)."""
    combos = []
    for k, ew, vm in itertools.product(
        STOCH_K_VALUES,
        ENTRY_WINDOW_VALUES,
        VOL_MIN_RATIO_VALUES,
    ):
        p = dict(V3_FIXED)
        p["stoch_k"]       = k
        p["entry_window"]  = ew
        p["vol_min_ratio"] = vm
        combos.append(p)
    return combos


# -- Hard filters and basket scoring ---------------------------

MIN_COIN_COVERAGE   = 0.7   # fraction of coins that must have trades
MIN_POSITIVE_SHARPE = 5     # coins with Sharpe > 0
MIN_PROFITABLE      = 5     # coins with positive return
MAX_WORST_DD        = -25.0 # worst single-coin drawdown allowed
MIN_AVG_TRADES      = 3     # minimum avg trades per coin


def normalize_result(r: dict) -> dict:
    """Normalize engine output keys to consistent internal names."""
    return {
        "n_trades":      r["n_trades"],
        "win_rate":      r["win_rate"],
        "total_return":  r["total_return"],
        "sharpe":        r["sharpe_ratio"],
        "max_dd":        r["max_drawdown"],
        "profit_factor": r["profit_factor"],
    }


def score_candidate(coin_results: dict):
    """
    coin_results: {coin: normalized_result_dict or None}
    Returns basket score dict or None if hard filters fail.
    """
    n_coins = len(coin_results)
    results = [r for r in coin_results.values() if r is not None]
    n_valid = len(results)

    if n_valid < n_coins * MIN_COIN_COVERAGE:
        return None

    sharpes = [r["sharpe"]       for r in results]
    returns = [r["total_return"] for r in results]
    dds     = [r["max_dd"]       for r in results]
    trades  = [r["n_trades"]     for r in results]

    n_pos_sharpe = sum(1 for s in sharpes if s > 0)
    n_profitable = sum(1 for r in returns if r > 0)
    worst_dd     = min(dds)
    avg_trades   = np.mean(trades)

    if n_pos_sharpe < MIN_POSITIVE_SHARPE:
        return None
    if n_profitable < MIN_PROFITABLE:
        return None
    if worst_dd < MAX_WORST_DD:
        return None
    if avg_trades < MIN_AVG_TRADES:
        return None

    avg_sharpe = np.mean(sharpes)
    avg_return = np.mean(returns)
    avg_dd     = np.mean(dds)
    calmar     = avg_return / abs(avg_dd) if avg_dd != 0 else 0.0

    return {
        "avg_sharpe":   round(avg_sharpe, 3),
        "avg_return":   round(avg_return, 2),
        "avg_dd":       round(avg_dd, 2),
        "worst_dd":     round(worst_dd, 2),
        "avg_calmar":   round(calmar, 3),
        "n_pos_sharpe": n_pos_sharpe,
        "n_profitable": n_profitable,
        "avg_trades":   round(avg_trades, 1),
        "n_coins":      n_valid,
    }


# -- Signal + engine helpers -----------------------------------

def run_on_train(df_full, params, window):
    """Run signal on train window, return normalized result or None."""
    df_train = df_full[
        (df_full.index >= window["train_start"]) &
        (df_full.index <  window["train_end"])
    ]
    if len(df_train) < 500:
        return None
    try:
        _, _, _, _, df_sig = get_entries_exits(df_train, params)
        if df_sig is None or len(df_sig) < 30:
            return None
        raw = engine_run_backtest(df_sig)
        if "error" in raw:
            return None
        return normalize_result(raw)
    except Exception:
        return None


def run_on_oos(df_full, params, window):
    """
    Run signal on data up to test_end, slice to OOS period,
    return normalized result or None.
    """
    df_up_to_end = df_full[df_full.index < window["test_end"]]
    try:
        _, _, _, _, df_sig_full = get_entries_exits(df_up_to_end, params)
        if df_sig_full is None:
            return None
        df_sig_oos = df_sig_full[
            (df_sig_full.index >= window["test_start"]) &
            (df_sig_full.index <  window["test_end"])
        ].copy()
        df_sig_oos.attrs = df_sig_full.attrs
        if len(df_sig_oos) < 20:
            return None
        raw = engine_run_backtest(df_sig_oos)
        if "error" in raw:
            return None
        return normalize_result(raw)
    except Exception:
        return None


# -- Window builder --------------------------------------------

def build_windows():
    anchor  = pd.Timestamp(ANCHOR_START, tz="UTC")
    windows = []
    for i in range(N_WINDOWS):
        test_start = anchor + relativedelta(months=TRAIN_MONTHS + i * TEST_MONTHS)
        test_end   = test_start + relativedelta(months=TEST_MONTHS)
        windows.append({
            "window":      i + 1,
            "train_start": anchor,
            "train_end":   test_start,
            "test_start":  test_start,
            "test_end":    test_end,
        })
    return windows


# -- Main optimizer --------------------------------------------

def run_optimizer(coins):
    param_grid = get_param_grid()
    windows    = build_windows()
    out_dir    = Path("results/optimize")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 72)
    print("  StochVol V3 -- Stage 2 Basket Optimizer")
    print(f"  {len(param_grid)} param combos  x  {len(coins)} coins  x  {N_WINDOWS} windows")
    print(f"  Coins : {', '.join(coins)}")
    print(f"  Anchor: {ANCHOR_START}  |  Train: {TRAIN_MONTHS}m  |  OOS: {TEST_MONTHS}m")
    print("=" * 72)

    print("\n  Loading candle data...")
    candles = {}
    for coin in coins:
        try:
            candles[coin] = load_candles(coin, "5m")
            print(f"    OK  {coin:<6} {len(candles[coin]):>7,} candles")
        except FileNotFoundError:
            print(f"    SKIP {coin}: no data")
    coins = [c for c in coins if c in candles]

    if not coins:
        print("No coin data found.")
        return

    basket_summaries = []

    for w in windows:
        print(f"\n{'='*72}")
        print(f"  Window {w['window']}")
        print(f"  Train : {w['train_start'].date()} -> {w['train_end'].date()}")
        print(f"  OOS   : {w['test_start'].date()} -> {w['test_end'].date()}")
        print(f"  Running {len(param_grid)} combos across {len(coins)} coins...\n")

        leaderboard = []
        n_rejected  = 0

        for params in param_grid:
            coin_results = {}
            for coin in coins:
                coin_results[coin] = run_on_train(candles[coin], params, w)

            score = score_candidate(coin_results)
            if score is None:
                n_rejected += 1
                continue

            leaderboard.append({
                "stoch_k":       params["stoch_k"],
                "entry_window":  params["entry_window"],
                "vol_min_ratio": params["vol_min_ratio"],
                **score,
            })

        n_passed = len(leaderboard)
        print(f"  Passed  : {n_passed}/{len(param_grid)}")
        print(f"  Rejected: {n_rejected}/{len(param_grid)}\n")

        if not leaderboard:
            print(f"  No combos passed filters for W{w['window']}")
            continue

        lb_df = pd.DataFrame(leaderboard).sort_values(
            ["avg_sharpe", "avg_calmar", "worst_dd"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        lb_df.insert(0, "rank", range(1, len(lb_df) + 1))

        lb_df.to_csv(out_dir / f"train_leaderboard_W{w['window']}.csv", index=False)

        print("  Top 5 train combos:")
        print(f"  {'Rank':>4}  {'k':>4}  {'ew':>4}  {'vm':>5}  "
              f"{'Sharpe':>8}  {'Return':>8}  {'DD':>7}  {'Calmar':>7}")
        print("  " + "-" * 62)
        for _, row in lb_df.head(5).iterrows():
            v3_tag = " <- V3" if (int(row["stoch_k"]) == 21 and
                                   int(row["entry_window"]) == 3 and
                                   float(row["vol_min_ratio"]) == 0.5) else ""
            print(f"  {int(row['rank']):>4}  "
                  f"{int(row['stoch_k']):>4}  "
                  f"{int(row['entry_window']):>4}  "
                  f"{row['vol_min_ratio']:>5.1f}  "
                  f"{row['avg_sharpe']:>8.2f}  "
                  f"{row['avg_return']:>+7.1f}%  "
                  f"{row['avg_dd']:>6.1f}%  "
                  f"{row['avg_calmar']:>7.2f}"
                  f"{v3_tag}")

        best = lb_df.iloc[0]
        selected_params = dict(V3_FIXED)
        selected_params["stoch_k"]       = int(best["stoch_k"])
        selected_params["entry_window"]  = int(best["entry_window"])
        selected_params["vol_min_ratio"] = float(best["vol_min_ratio"])

        with open(out_dir / f"selected_params_W{w['window']}.json", "w") as f:
            json.dump(selected_params, f, indent=2)

        print(f"\n  Winner: k={selected_params['stoch_k']}  "
              f"ew={selected_params['entry_window']}  "
              f"vm={selected_params['vol_min_ratio']}")
        print(f"  Train  avg Sharpe: {best['avg_sharpe']:.2f}  "
              f"Return: {best['avg_return']:+.1f}%  "
              f"DD: {best['avg_dd']:.1f}%")

        print(f"\n  OOS evaluation...")
        oos_rows = []
        for coin in coins:
            r = run_on_oos(candles[coin], selected_params, w)
            if r:
                status = "OK " if r["total_return"] > 0 else "BAD"
                print(f"    {coin:<6}  {status}  "
                      f"Sharpe: {r['sharpe']:>6.2f}  "
                      f"Return: {r['total_return']:>+7.1f}%  "
                      f"DD: {r['max_dd']:>6.1f}%  "
                      f"Trades: {r['n_trades']}")
                oos_rows.append({
                    "window":        f"W{w['window']}",
                    "coin":          coin,
                    "n_trades":      r["n_trades"],
                    "sharpe":        r["sharpe"],
                    "total_return":  r["total_return"],
                    "win_rate":      r["win_rate"],
                    "max_dd":        r["max_dd"],
                    "profit_factor": r["profit_factor"],
                })
            else:
                print(f"    {coin:<6}  ---   no trades in OOS")

        if oos_rows:
            oos_df = pd.DataFrame(oos_rows)
            oos_df.to_csv(out_dir / f"oos_results_W{w['window']}.csv", index=False)

            oos_avg_sharpe = oos_df["sharpe"].mean()
            oos_avg_return = oos_df["total_return"].mean()
            oos_avg_dd     = oos_df["max_dd"].mean()
            oos_profitable = (oos_df["total_return"] > 0).sum()
            oos_worst_coin = oos_df.loc[oos_df["sharpe"].idxmin(), "coin"]

            print(f"\n  OOS basket  Sharpe: {oos_avg_sharpe:.2f}  "
                  f"Return: {oos_avg_return:+.1f}%  "
                  f"DD: {oos_avg_dd:.1f}%  "
                  f"Profitable: {oos_profitable}/{len(oos_rows)}  "
                  f"Worst: {oos_worst_coin}")

            is_v3 = (selected_params["stoch_k"] == 21 and
                     selected_params["entry_window"] == 3 and
                     selected_params["vol_min_ratio"] == 0.5)

            basket_summaries.append({
                "window":           f"W{w['window']}",
                "stoch_k":          selected_params["stoch_k"],
                "entry_window":     selected_params["entry_window"],
                "vol_min_ratio":    selected_params["vol_min_ratio"],
                "is_v3_default":    is_v3,
                "train_avg_sharpe": round(float(best["avg_sharpe"]), 2),
                "train_avg_return": round(float(best["avg_return"]), 1),
                "oos_avg_sharpe":   round(oos_avg_sharpe, 2),
                "oos_avg_return":   round(oos_avg_return, 1),
                "oos_avg_dd":       round(oos_avg_dd, 1),
                "oos_profitable":   f"{oos_profitable}/{len(oos_rows)}",
                "oos_worst_coin":   oos_worst_coin,
                "n_combos_passed":  n_passed,
            })

    # -- Final summary -----------------------------------------
    if not basket_summaries:
        print("\nNo windows produced results.")
        return

    summary_df = pd.DataFrame(basket_summaries)
    summary_df.to_csv(out_dir / "basket_summary.csv", index=False)

    print("\n\n" + "=" * 72)
    print("  Basket Optimizer -- Final Summary")
    print("=" * 72)
    print(tabulate(
        summary_df[[
            "window", "stoch_k", "entry_window", "vol_min_ratio",
            "train_avg_sharpe", "oos_avg_sharpe", "oos_avg_return",
            "oos_avg_dd", "oos_profitable", "is_v3_default",
        ]],
        headers="keys",
        tablefmt="rounded_outline",
        showindex=False,
        floatfmt=".2f",
    ))

    v3_wins = summary_df["is_v3_default"].sum()
    print(f"\n  V3 defaults won {v3_wins}/{len(summary_df)} windows")
    print(f"  (stoch_k=21, entry_window=3, vol_min_ratio=0.5)")
    print(f"\n  All artifacts -> {out_dir}/")


# -- CLI -------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="StochVol V3 Stage 2 basket optimizer"
    )
    parser.add_argument(
        "--coins", nargs="+",
        default=COINS_DEFAULT,
        help="Coins to include (default: 7-coin basket)"
    )
    args = parser.parse_args()
    run_optimizer(args.coins)

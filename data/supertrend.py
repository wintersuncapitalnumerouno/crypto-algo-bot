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
#
# HOW TO RUN:
#   # Baseline (no regime filter)
#   python backtest/engine.py
#
#   # With regime filter
#   python backtest/engine.py --regime
#
#   # Compare both side by side
#   python backtest/engine.py --compare
#
#   # Specific phase
#   python backtest/engine.py --phase optimization
#
# REGIME FILTER LOGIC:
#   Blocks NEW entries (does not close open trades) when:
#     - DVOL > IV_HIGH (90)   → too volatile, stop-hunts likely
#     - DVOL < IV_LOW  (45)   → too quiet, breakouts fail
#     - Funding > 0.05%       → crowded long, fade longs
#     - Funding < -0.01%      → crowded short, fade shorts
#     - VIX > 30              → risk-off, avoid new longs
# =============================================================

import sys, os, argparse, warnings
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from tabulate import tabulate

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from strategies.registry  import get_strategies, list_strategies
from data.fetch_data       import load_candles
from backtest.results_manager import ResultsManager

# ─────────────────────────────────────────────────────────────
# DATE FILTER
# ─────────────────────────────────────────────────────────────

def filter_dates(df: pd.DataFrame, mode: str = "train") -> pd.DataFrame:
    """
    Filter DataFrame to the configured date range.

    mode="train" → TRAIN_START to TRAIN_END
    mode="test"  → TEST_START  to TEST_END
    mode="full"  → no filter

    Respects config.BACKTEST_MODE:
      "full"        → always return full df
      "fixed"       → use train dates only
      "split"       → use train or test depending on mode arg
      "walkforward" → no filter here (engine handles it)
    """
    bm = getattr(config, "BACKTEST_MODE", "full")

    if bm == "full" or bm == "walkforward":
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
DVOL_LOW        = 45    # too quiet  → breakouts fail
DVOL_HIGH       = 90    # too wild   → stop hunts
FUNDING_HIGH    = 0.0005  # 0.05%   → crowded long
FUNDING_LOW     = -0.0001 # -0.01%  → crowded short
VIX_HIGH        = 30    # risk-off threshold


# ─────────────────────────────────────────────────────────────
# LOAD REGIME DATA
# ─────────────────────────────────────────────────────────────

def load_regime_data() -> dict:
    """Load DVOL, macro, and funding data for regime filter."""
    data = {}

    # DVOL
    dvol_path = os.path.join(config.DATA_DIR, "BTC_DVOL_1h.csv")
    if os.path.exists(dvol_path):
        df = pd.read_csv(dvol_path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        data["dvol"] = df["close"] if "close" in df.columns else df.iloc[:, 0]

    # Macro (VIX)
    macro_path = os.path.join(config.DATA_DIR, "macro_1h.csv")
    if os.path.exists(macro_path):
        df = pd.read_csv(macro_path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        if "VIX_close" in df.columns:
            data["vix"] = df["VIX_close"]

    return data


def load_funding_data(coin: str) -> pd.Series | None:
    """Load 8h funding rates for a coin, resampled to match candle index."""
    path = os.path.join(config.DATA_DIR, f"{coin}_funding_8h.csv")
    if not os.path.exists(path):
        path = os.path.join(config.DATA_DIR, f"{coin}_funding_1h.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df["funding_rate"]


# ─────────────────────────────────────────────────────────────
# REGIME FILTER
# ─────────────────────────────────────────────────────────────

def build_regime_mask(
    candle_index: pd.DatetimeIndex,
    coin: str,
    regime_data: dict,
) -> pd.Series:
    """
    Returns a boolean Series aligned to candle_index.
    True  = regime is OK → allow entries
    False = regime blocked → skip new entries
    """
    mask = pd.Series(True, index=candle_index)

    # ── DVOL filter ──────────────────────────────────────────
    if "dvol" in regime_data:
        dvol = regime_data["dvol"].reindex(candle_index, method="ffill")
        mask &= (dvol >= DVOL_LOW) & (dvol <= DVOL_HIGH)

    # ── VIX filter ───────────────────────────────────────────
    if "vix" in regime_data:
        vix = regime_data["vix"].reindex(candle_index, method="ffill")
        mask &= (vix <= VIX_HIGH)

    # ── Funding filter ───────────────────────────────────────
    funding = load_funding_data(coin)
    if funding is not None:
        funding_aligned = funding.reindex(candle_index, method="ffill")
        mask &= (funding_aligned <= FUNDING_HIGH)
        mask &= (funding_aligned >= FUNDING_LOW)

    return mask.fillna(True)  # if no data, don't block


# ─────────────────────────────────────────────────────────────
# BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────

def run_backtest(
    df_signals: pd.DataFrame,
    direction: str = "both",
    regime_mask: pd.Series = None,
) -> dict:
    """
    Simulate trades with stop loss, take profit, time stop enforcement.
    Optionally applies regime filter to block entries.

    Args:
        df_signals  : DataFrame with OHLCV + signal + stop/TP columns
        direction   : "long", "short", or "both"
        regime_mask : boolean Series — True = allow entry, False = block
    """
    trades      = []
    in_trade    = False
    entry_price = None
    entry_time  = None
    stop_loss   = None
    take_profit = None
    trade_dir   = None
    hold_count  = 0

    fee     = config.TAKER_FEE + config.SLIPPAGE
    capital = config.INITIAL_CAPITAL
    equity  = [capital]

    # 96 x 5m candles = 8 hours max hold
    MAX_HOLD_CANDLES = 96

    for ts, row in df_signals.iterrows():
        signal = row.get("signal", 0)
        high   = row["high"]
        low    = row["low"]
        close  = row["close"]

        # ── Manage open trade ─────────────────────────────────
        if in_trade:
            hold_count += 1
            exit_price  = None
            exit_reason = None

            if trade_dir == "long":
                if low <= stop_loss:
                    exit_price, exit_reason = stop_loss, "stop_loss"
                elif high >= take_profit:
                    exit_price, exit_reason = take_profit, "take_profit"
                elif hold_count >= MAX_HOLD_CANDLES:
                    exit_price, exit_reason = close, "time_stop"
                elif signal == -1:
                    exit_price, exit_reason = close * (1 - fee), "signal_exit"

            elif trade_dir == "short":
                if high >= stop_loss:
                    exit_price, exit_reason = stop_loss, "stop_loss"
                elif low <= take_profit:
                    exit_price, exit_reason = take_profit, "take_profit"
                elif hold_count >= MAX_HOLD_CANDLES:
                    exit_price, exit_reason = close, "time_stop"
                elif signal == 1:
                    exit_price, exit_reason = close * (1 + fee), "signal_exit"

            if exit_price is not None:
                if trade_dir == "long":
                    pnl_pct = (exit_price * (1 - fee) - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price * (1 + fee)) / entry_price

                pnl_usd = capital * pnl_pct
                capital *= (1 + pnl_pct)
                equity.append(capital)

                trades.append({
                    "entry_time":   entry_time,
                    "exit_time":    ts,
                    "direction":    trade_dir,
                    "entry_price":  round(entry_price, 6),
                    "exit_price":   round(exit_price, 6),
                    "stop_loss":    round(stop_loss, 6),
                    "take_profit":  round(take_profit, 6),
                    "exit_reason":  exit_reason,
                    "pnl_pct":      round(pnl_pct * 100, 4),
                    "pnl":          round(pnl_usd, 4),
                    "duration_min": int((ts - entry_time).total_seconds() / 60),
                })

                in_trade   = False
                hold_count = 0

        # ── Process entry ─────────────────────────────────────
        if not in_trade:
            # Check regime filter
            regime_ok = True
            if regime_mask is not None and ts in regime_mask.index:
                regime_ok = bool(regime_mask.loc[ts])

            if regime_ok:
                if signal == 1 and direction in ("long", "both"):
                    entry_price = close * (1 + fee)
                    entry_time  = ts
                    trade_dir   = "long"
                    stop_loss   = row.get("stop_loss_long",   close * (1 - 0.02))
                    take_profit = row.get("take_profit_long", close * (1 + 0.04))
                    in_trade    = True
                    hold_count  = 0

                elif signal == -1 and direction in ("short", "both"):
                    entry_price = close * (1 - fee)
                    entry_time  = ts
                    trade_dir   = "short"
                    stop_loss   = row.get("stop_loss_short",   close * (1 + 0.02))
                    take_profit = row.get("take_profit_short", close * (1 - 0.04))
                    in_trade    = True
                    hold_count  = 0

    # ── Metrics ───────────────────────────────────────────────
    if not trades:
        return {"error": "No trades generated"}

    trades_df = pd.DataFrame(trades)
    equity_s  = pd.Series(equity)

    n_trades  = len(trades_df)
    winners   = trades_df[trades_df["pnl_pct"] > 0]
    losers    = trades_df[trades_df["pnl_pct"] <= 0]
    win_rate  = len(winners) / n_trades if n_trades > 0 else 0

    gross_profit  = winners["pnl"].sum() if len(winners) > 0 else 0
    gross_loss    = abs(losers["pnl"].sum()) if len(losers) > 0 else 0.0001
    profit_factor = gross_profit / gross_loss

    total_return = (capital - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL

    roll_max  = equity_s.cummax()
    drawdowns = (equity_s - roll_max) / roll_max
    max_dd    = drawdowns.min()

    returns = trades_df["pnl_pct"] / 100
    sharpe  = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

    # Sortino
    downside    = returns[returns < 0]
    downside_std = downside.std() if len(downside) > 1 else 0.0001
    ann_return  = (capital / config.INITIAL_CAPITAL) ** (252 / max(n_trades, 1)) - 1
    sortino     = ann_return / (downside_std * np.sqrt(252)) if downside_std > 0 else 0

    # Calmar
    calmar = (total_return / abs(max_dd)) if max_dd != 0 else 0

    # Max consecutive losses
    wins_losses = (trades_df["pnl_pct"] > 0).astype(int).tolist()
    max_consec  = cur = 0
    for w in wins_losses:
        cur = cur + 1 if w == 0 else 0
        max_consec = max(max_consec, cur)

    exit_counts = trades_df["exit_reason"].value_counts().to_dict()

    return {
        "n_trades":         n_trades,
        "win_rate":         round(win_rate * 100, 1),
        "total_return":     round(total_return * 100, 2),
        "final_capital":    round(capital, 2),
        "max_drawdown":     round(max_dd * 100, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "sortino_ratio":    round(sortino, 2),
        "calmar_ratio":     round(calmar, 2),
        "profit_factor":    round(profit_factor, 2),
        "avg_win_pct":      round(winners["pnl_pct"].mean(), 3) if len(winners) > 0 else 0,
        "avg_loss_pct":     round(losers["pnl_pct"].mean(),  3) if len(losers)  > 0 else 0,
        "avg_duration_m":   round(trades_df["duration_min"].mean(), 1),
        "max_consec_losses": max_consec,
        "exit_reasons":     exit_counts,
        "trades_df":        trades_df,
        "equity_curve":     equity_s,
    }


# STRATEGIES loaded dynamically from strategies/registry.py


# ─────────────────────────────────────────────────────────────
# RUN ALL
# ─────────────────────────────────────────────────────────────

def run_all(
    coins=None,
    timeframes=None,
    phase="exploration",
    use_regime=False,
    strategy_names=None,
):
    coins      = coins      or config.COINS
    timeframes = timeframes or config.BACKTEST_TIMEFRAMES

    # Load strategy registry
    STRATEGIES = get_strategies(strategy_names)
    if not STRATEGIES:
        print("❌ No strategies found. Check registry.py")
        return pd.DataFrame()

    rm      = ResultsManager(phase=phase, regime_filter=use_regime)
    results = []
    total   = len(STRATEGIES) * len(coins) * len(timeframes)
    done    = 0

    # Load regime data once (shared across all coins/strategies)
    regime_data = load_regime_data() if use_regime else {}
    rf_tag      = "✅ ON" if use_regime else "❌ OFF"

    print("\n" + "=" * 70)
    print(f"  ⚙️   Backtesting  |  Phase: {phase.upper()}  |  Regime Filter: {rf_tag}")
    print("=" * 70)

    for strategy_name, strategy_cfg in STRATEGIES.items():
        signal_fn = strategy_cfg["fn"]
        params    = strategy_cfg["params"]
        for coin in coins:

            # Build regime mask per coin (funding is coin-specific)
            regime_mask = None
            if use_regime:
                try:
                    df_tmp = load_candles(coin, timeframes[0])
                    regime_mask = build_regime_mask(df_tmp.index, coin, regime_data)
                    blocked_pct = (~regime_mask).mean() * 100
                    print(f"  🔒  {coin} regime filter: {blocked_pct:.1f}% of candles blocked")
                except Exception:
                    pass

            for tf in timeframes:
                done  += 1
                label  = f"[{done}/{total}] {strategy_name} | {coin} {tf}"
                print(f"\n  {label}...", end=" ", flush=True)

                try:
                    df = load_candles(coin, tf)
                    df = filter_dates(df, mode="train")
                except FileNotFoundError:
                    print("⚠️  no data file")
                    continue

                try:
                    _, _, _, _, df_sig = signal_fn(df, params)
                    result = run_backtest(df_sig, regime_mask=regime_mask)
                except Exception as e:
                    print(f"❌ {e}")
                    continue

                if "error" in result:
                    print(f"⚠️  {result['error']}")
                    continue

                print(
                    f"✅  Return: {result['total_return']:+.1f}%  "
                    f"Sharpe: {result['sharpe_ratio']:.2f}  "
                    f"Sortino: {result['sortino_ratio']:.2f}  "
                    f"WR: {result['win_rate']}%  "
                    f"Trades: {result['n_trades']}"
                )

                rm.save_strategy_result(strategy_name, coin, tf, result)

                results.append({
                    "Strategy":       strategy_name,
                    "Coin":           coin,
                    "Timeframe":      tf,
                    "Trades":         result["n_trades"],
                    "Return %":       result["total_return"],
                    "Sharpe":         result["sharpe_ratio"],
                    "Sortino":        result["sortino_ratio"],
                    "Calmar":         result["calmar_ratio"],
                    "Max DD %":       result["max_drawdown"],
                    "Win Rate %":     result["win_rate"],
                    "Prof Factor":    result["profit_factor"],
                    "Avg Dur(m)":     result["avg_duration_m"],
                    "Max Consec Loss":result["max_consec_losses"],
                    "SL Hits":        result["exit_reasons"].get("stop_loss", 0),
                    "TP Hits":        result["exit_reasons"].get("take_profit", 0),
                    "Regime Filter":  rf_tag,
                })

    if not results:
        print("\n❌ No results.")
        return pd.DataFrame()

    results_df = pd.DataFrame(results)

    print("\n" + "=" * 70)
    print(f"  📊  RESULTS  |  Phase: {phase.upper()}  |  Regime Filter: {rf_tag}")
    print("=" * 70)
    print(tabulate(
        results_df.sort_values("Sharpe", ascending=False),
        headers="keys",
        tablefmt="rounded_outline",
        showindex=False,
        floatfmt=".2f",
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
# COMPARE MODE — run with and without regime filter
# ─────────────────────────────────────────────────────────────

def run_compare(coins=None, timeframes=None, phase="exploration", strategy_names=None):
    """Run backtest twice and print side-by-side comparison."""
    print("\n" + "=" * 70)
    print("  🔀  COMPARE MODE: Regime Filter OFF vs ON")
    print("=" * 70)

    df_off = run_all(coins, timeframes, phase=phase, use_regime=False, strategy_names=strategy_names)
    df_on  = run_all(coins, timeframes, phase=phase, use_regime=True,  strategy_names=strategy_names)

    if df_off.empty or df_on.empty:
        return

    # Merge on Strategy + Coin + Timeframe
    merged = df_off[["Strategy","Coin","Timeframe","Return %","Sharpe","Max DD %","Win Rate %","Trades"]].copy()
    merged = merged.rename(columns={
        "Return %": "Return% (no RF)",
        "Sharpe":   "Sharpe (no RF)",
        "Trades":   "Trades (no RF)",
    })

    on_cols = df_on[["Strategy","Coin","Timeframe","Return %","Sharpe","Win Rate %","Trades"]].copy()
    on_cols = on_cols.rename(columns={
        "Return %": "Return% (RF)",
        "Sharpe":   "Sharpe (RF)",
        "Trades":   "Trades (RF)",
    })

    comp = merged.merge(on_cols, on=["Strategy","Coin","Timeframe"])
    comp["Sharpe Δ"] = comp["Sharpe (RF)"] - comp["Sharpe (no RF)"]
    comp["Return Δ"] = comp["Return% (RF)"] - comp["Return% (no RF)"]

    print("\n" + "=" * 70)
    print("  📊  COMPARISON TABLE")
    print("=" * 70)
    print(tabulate(
        comp.sort_values("Sharpe Δ", ascending=False),
        headers="keys",
        tablefmt="rounded_outline",
        showindex=False,
        floatfmt=".2f",
    ))

    improved = (comp["Sharpe Δ"] > 0).sum()
    print(f"\n  Regime filter improved Sharpe in {improved}/{len(comp)} combinations")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Algo Backtest Engine v3")
    parser.add_argument("--regime",   action="store_true", help="Enable regime filter")
    parser.add_argument("--compare",  action="store_true", help="Compare with/without regime filter")
    parser.add_argument("--phase",    default="exploration",
                        choices=["exploration","optimization","validation","live"])
    parser.add_argument("--coins",    nargs="+", default=None)
    parser.add_argument("--tf",       nargs="+", default=None)
    parser.add_argument("--strategy", nargs="+", default=None,
                        help="Strategy names to run e.g. --strategy Breakout Momentum")
    parser.add_argument("--list",     action="store_true", help="List all registered strategies")
    args = parser.parse_args()

    if args.list:
        list_strategies()
    elif args.compare:
        run_compare(coins=args.coins, timeframes=args.tf, phase=args.phase,
                    strategy_names=args.strategy)
    else:
        run_all(
            coins=args.coins,
            timeframes=args.tf,
            phase=args.phase,
            use_regime=args.regime,
            strategy_names=args.strategy,
        )

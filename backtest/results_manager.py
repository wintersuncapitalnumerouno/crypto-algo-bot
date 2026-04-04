# =============================================================
# backtest/results_manager.py
# =============================================================
#
# Folder structure:
#   results/{phase}/{Strategy}/{version-tag}/{timestamp}/
#
# Example:
#   results/exploration/EMA16/v4__4h_scaled_exits/20260316_1200/
#   results/exploration/Momentum/v2__15m_adx_htf/20260316_0900/
#
# run_tag is REQUIRED — engine raises if not provided.
# This enforces intentional versioning on every run.
#
# =============================================================

import os, sys, json, argparse
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

PHASES = ["exploration", "optimization", "validation", "live"]


class ResultsManager:

    def __init__(
        self,
        phase:         str  = "exploration",
        regime_filter: bool = False,
        date_tag:      str  = None,
        strategy_name: str  = None,
        run_tag:       str  = None,
    ):
        if phase not in PHASES:
            raise ValueError(f"Phase must be one of {PHASES}")

        if not run_tag:
            raise ValueError(
                "\n\n  ❌ --tag is required.\n"
                "  Every run must be tagged so results are traceable.\n\n"
                "  Example:\n"
                "    python backtest/engine.py --strategy EMA16 --tag v4__4h_scaled_exits\n"
                "    python backtest/engine.py --strategy Momentum --tag v1__15m_baseline\n"
            )

        self.phase         = phase
        self.regime_filter = regime_filter
        self.date_tag      = date_tag
        self.strategy_name = strategy_name or "Unknown"
        self.run_tag       = run_tag
        self.run_dir       = self._make_run_dir()
        self.run_name      = self.run_dir.name

        print(f"\n  📁 Phase      : {phase.upper()}")
        print(f"  📁 Strategy   : {self.strategy_name}")
        print(f"  📁 Version    : {self.run_tag}")
        print(f"  📁 Run        : {self.run_name}")
        print(f"  📁 Folder     : {self.run_dir}")

    def _make_run_dir(self) -> Path:
        ts   = datetime.now().strftime("%Y%m%d_%H%M")
        rf   = "_RF" if self.regime_filter else ""
        dt   = f"_{self.date_tag}" if self.date_tag else ""
        name = f"{ts}{rf}{dt}"

        base = (
            Path(config.RESULTS_DIR)
            / self.phase
            / self.strategy_name
            / self.run_tag
        )
        base.mkdir(parents=True, exist_ok=True)

        run_dir = base / name
        counter = 2
        while run_dir.exists():
            run_dir = base / f"{name}_{counter}"
            counter += 1

        run_dir.mkdir(parents=True)
        return run_dir

    def save_metadata(self, extra: dict = None):
        try:
            from strategies.registry import get_strategies
            strategy_params = {
                name: cfg.get("params", {})
                for name, cfg in get_strategies().items()
            }
        except Exception:
            strategy_params = {}

        metadata = {
            "run_name":        self.run_name,
            "strategy_name":   self.strategy_name,
            "run_tag":         self.run_tag,
            "phase":           self.phase,
            "timestamp":       datetime.now().isoformat(),
            "regime_filter":   self.regime_filter,
            "date_tag":        self.date_tag,
            "coins":           config.COINS,
            "timeframes":      config.BACKTEST_TIMEFRAMES,
            "initial_capital": config.INITIAL_CAPITAL,
            "taker_fee":       config.TAKER_FEE,
            "slippage":        config.SLIPPAGE,
            "leverage":        getattr(config, "LEVERAGE", 1),
            "risk_pct":        getattr(config, "RISK_PCT", 0.005),
            "stop_pct":        getattr(config, "STOP_PCT", 0.02),
            "strategy_params": strategy_params,
        }
        if extra:
            metadata.update(extra)

        with open(self.run_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        print(f"  📋 Metadata saved → {self.run_dir / 'metadata.json'}")

    @staticmethod
    def compute_parent_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregate partial exit rows into one row per parent trade.

        For strategies using scaled exits, each trade_id has multiple rows:
          - tp1_, tp2_, tp3_ partial exits
          - trail_stop / stop_loss / signal_exit / time_stop final exit

        This produces trades_parent.csv with honest per-trade stats:
          - true total PnL (sum of all partial + final)
          - true duration (entry_time → last exit_time)
          - combined position size
          - overall winner/loser classification
          - which TP levels were hit
        """
        if trades_df.empty or "trade_id" not in trades_df.columns:
            return pd.DataFrame()

        rows = []
        for trade_id, group in trades_df.groupby("trade_id", sort=False):
            group = group.sort_values("exit_time")

            # Exit reasons
            exit_reasons = group["exit_reason"].tolist()
            tp_hits      = [r for r in exit_reasons if r.startswith("tp")]
            final_reason = exit_reasons[-1] if not exit_reasons[-1].startswith("tp") else "full_tp"

            # PnL — weighted by position size
            total_pnl_usd  = group["pnl"].sum()
            total_size_usd = group["position_size_usd"].sum()
            total_pnl_pct  = (total_pnl_usd / group["equity_at_entry"].iloc[0] * 100) if group["equity_at_entry"].iloc[0] > 0 else 0

            rows.append({
                "trade_id":        trade_id,
                "entry_time":      group["entry_time"].iloc[0],
                "exit_time":       group["exit_time"].iloc[-1],
                "direction":       group["direction"].iloc[0],
                "entry_price":     group["entry_price"].iloc[0],
                "final_exit_price":group["exit_price"].iloc[-1],
                "equity_at_entry": group["equity_at_entry"].iloc[0],
                "total_size_usd":  round(total_size_usd, 2),
                "total_pnl_usd":   round(total_pnl_usd, 4),
                "total_pnl_pct":   round(total_pnl_pct, 4),
                "winner":          total_pnl_usd > 0,
                "duration_min":    int((group["exit_time"].iloc[-1] - group["entry_time"].iloc[0]).total_seconds() / 60),
                "n_partials":      len(tp_hits),
                "tp_levels_hit":   ", ".join(tp_hits) if tp_hits else "none",
                "final_exit":      final_reason,
                "r_multiple":      round(group["r_multiple"].sum(), 3),
            })

        parent_df = pd.DataFrame(rows)
        return parent_df

    @staticmethod
    def compute_metrics(result: dict, equity_curve: pd.Series = None) -> dict:
        m = dict(result)
        if equity_curve is not None and len(equity_curve) > 1:
            returns      = equity_curve.pct_change().dropna()
            downside     = returns[returns < 0]
            downside_std = downside.std() * np.sqrt(365 * 24)
            ann_return   = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (
                365 * 24 / len(equity_curve)) - 1
            m["sortino_ratio"] = (ann_return / downside_std) if downside_std > 0 else 0
            max_dd = m.get("max_drawdown", 0)
            m["calmar_ratio"]  = (ann_return / abs(max_dd / 100)) if max_dd != 0 else 0
            eq_df  = equity_curve.to_frame("equity")
            eq_df.index = pd.to_datetime(eq_df.index)
            monthly = eq_df["equity"].resample("ME").last().pct_change().dropna() * 100
            m["monthly_returns"] = monthly
        if "trades_df" in result and not result["trades_df"].empty:
            trades = result["trades_df"]
            if "pnl" in trades.columns:
                wl = (trades["pnl"] > 0).astype(int)
                max_consec = cur = 0
                for w in wl:
                    cur = cur + 1 if w == 0 else 0
                    max_consec = max(max_consec, cur)
                m["max_consec_losses"] = max_consec
        return m

    def save_summary(self, results_df: pd.DataFrame):
        results_df.to_csv(self.run_dir / "summary.csv", index=False)

        rf_tag  = "✅ ON" if self.regime_filter else "❌ OFF"
        dt_line = f"**Date Range:** {self.date_tag}" if self.date_tag else "**Date Range:** Full history"

        md_lines = [
            f"# {self.strategy_name} / {self.run_tag} / {self.run_name}",
            f"**Strategy:** {self.strategy_name}",
            f"**Version tag:** `{self.run_tag}`",
            f"**Phase:** {self.phase.upper()}",
            f"**Run at:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            dt_line,
            f"**Coins:** {', '.join(config.COINS)}",
            f"**Capital:** ${config.INITIAL_CAPITAL:,}",
            f"**Regime Filter:** {rf_tag}",
            "",
            "## Results (sorted by Sharpe)",
            "",
        ]

        if not results_df.empty and "Sharpe" in results_df.columns:
            md_lines.append(
                results_df.sort_values("Sharpe", ascending=False).to_markdown(index=False)
            )
            best = results_df.loc[results_df["Sharpe"].idxmax()]
            md_lines += [
                "",
                f"## 🏆 Best: {best.get('Coin','?')}",
                f"- Return  : **{best.get('Return %', 0):+.2f}%**",
                f"- Sharpe  : **{best.get('Sharpe', 0):.2f}**",
                f"- Max DD  : **{best.get('Max DD %', 0):.2f}%**",
                f"- Win Rate: **{best.get('Win Rate %', 0)}%**",
            ]

        with open(self.run_dir / "summary.md", "w") as f:
            f.write("\n".join(md_lines))
        print(f"  📊 Summary saved ({len(results_df)} rows)")

    def save_strategy_result(self, strategy, coin, timeframe, result, bnh: float = None):
        folder = self.run_dir / f"{coin}_{timeframe}"
        folder.mkdir(exist_ok=True)

        equity_curve = None
        if "equity_curve" in result and result["equity_curve"] is not None:
            eq = result["equity_curve"]
            eq.to_csv(folder / "equity_curve.csv", header=["equity"])
            equity_curve = eq

        m = self.compute_metrics(result, equity_curve)

        if "trades_df" in result and not result["trades_df"].empty:
            trades_df = result["trades_df"]
            trades_df.to_csv(folder / "trades.csv", index=False)

            # ── Parent trade summary ──────────────────────────
            # Aggregates partial exits into one honest row per trade.
            # Saves trades_parent.csv alongside trades.csv.
            parent_df = self.compute_parent_trades(trades_df)
            if not parent_df.empty:
                parent_df.to_csv(folder / "trades_parent.csv", index=False)

                # Parent-level win rate and stats for metrics.txt
                m["parent_n_trades"]    = len(parent_df)
                m["parent_win_rate"]    = round(parent_df["winner"].mean() * 100, 1)
                m["parent_avg_pnl_pct"] = round(parent_df["total_pnl_pct"].mean(), 3)
                m["parent_avg_dur_min"] = round(parent_df["duration_min"].mean(), 1)
                m["parent_tp1_hits"]    = int(parent_df["tp_levels_hit"].str.contains("tp1").sum())
                m["parent_tp2_hits"]    = int(parent_df["tp_levels_hit"].str.contains("tp2").sum())
                m["parent_tp3_hits"]    = int(parent_df["tp_levels_hit"].str.contains("tp3").sum())

        if "monthly_returns" in m and isinstance(m["monthly_returns"], pd.Series):
            m["monthly_returns"].to_csv(folder / "monthly_returns.csv", header=["return_pct"])

        # Per-coin metadata.json
        coin_meta = {
            "strategy":        strategy,
            "run_tag":         self.run_tag,
            "coin":            coin,
            "timeframe":       timeframe,
            "phase":           self.phase,
            "date_tag":        self.date_tag or "full",
            "regime_filter":   self.regime_filter,
            "total_return":    m.get("total_return", 0),
            "sharpe_ratio":    m.get("sharpe_ratio", 0),
            "max_drawdown":    m.get("max_drawdown", 0),
            "win_rate":        m.get("win_rate", 0),
            "n_trades":        m.get("n_trades", 0),
            "buy_and_hold":    bnh,
            "alpha":           round(m.get("total_return", 0) - (bnh or 0), 2) if bnh else None,
        }
        with open(folder / "metadata.json", "w") as f:
            json.dump(coin_meta, f, indent=2, default=str)

        alpha  = round(m.get("total_return", 0) - (bnh or 0), 2) if bnh is not None else None
        rf_tag = "YES" if self.regime_filter else "NO"

        lines = [
            f"Strategy       : {strategy}",
            f"Version Tag    : {self.run_tag}",
            f"Coin           : {coin}",
            f"Timeframe      : {timeframe}",
            f"Phase          : {self.phase.upper()}",
            f"Date Range     : {self.date_tag or 'Full history'}",
            f"Regime Filter  : {rf_tag}",
            "─" * 40,
            "── RETURNS ─────────────────────────────",
            f"Total Return   : {m.get('total_return', 0):+.2f}%",
            f"Buy & Hold     : {bnh:+.2f}%" if bnh is not None else "Buy & Hold     : N/A",
            f"Alpha          : {alpha:+.2f}%" if alpha is not None else "Alpha          : N/A",
            f"Final Capital  : ${m.get('final_capital', 0):,.2f}",
            "",
            "── RISK-ADJUSTED ────────────────────────",
            f"Sharpe Ratio   : {m.get('sharpe_ratio', 0):.3f}",
            f"Sortino Ratio  : {m.get('sortino_ratio', 0):.3f}",
            f"Calmar Ratio   : {m.get('calmar_ratio', 0):.3f}",
            f"Max Drawdown   : {m.get('max_drawdown', 0):.2f}%",
            "",
            "── TRADE STATS (all rows) ───────────────",
            f"Total Rows     : {m.get('n_trades', 0)}",
            f"Win Rate       : {m.get('win_rate', 0)}%",
            f"Profit Factor  : {m.get('profit_factor', 0):.2f}",
            f"Avg Win        : {m.get('avg_win_pct', 0):+.3f}%",
            f"Avg Loss       : {m.get('avg_loss_pct', 0):+.3f}%",
            f"Avg Duration   : {m.get('avg_duration_m', 0):.0f} min",
            f"Max Consec Loss: {m.get('max_consec_losses', 0)}",
        ]

        # Parent trade stats (only meaningful when scaled exits are active)
        if m.get("parent_n_trades"):
            lines += [
                "",
                "── PARENT TRADE STATS (per trade_id) ───",
                f"Parent Trades  : {m.get('parent_n_trades', 0)}",
                f"Parent Win Rate: {m.get('parent_win_rate', 0)}%",
                f"Avg PnL/Trade  : {m.get('parent_avg_pnl_pct', 0):+.3f}%",
                f"Avg Duration   : {m.get('parent_avg_dur_min', 0):.0f} min",
                f"TP1 Hits       : {m.get('parent_tp1_hits', 0)}",
                f"TP2 Hits       : {m.get('parent_tp2_hits', 0)}",
                f"TP3 Hits       : {m.get('parent_tp3_hits', 0)}",
            ]

        if "monthly_returns" in m and isinstance(m["monthly_returns"], pd.Series):
            monthly = m["monthly_returns"]
            lines += ["", "── MONTHLY RETURNS ──────────────────────"]
            for date, ret in monthly.items():
                bar  = "█" * int(abs(ret) / 2)
                sign = "+" if ret >= 0 else ""
                lines.append(f"  {str(date)[:7]}  {sign}{ret:6.2f}%  {bar}")
            lines += [
                f"  Best month : {monthly.max():+.2f}%",
                f"  Worst month: {monthly.min():+.2f}%",
                f"  Positive   : {(monthly > 0).sum()}/{len(monthly)} months",
            ]

        with open(folder / "metrics.txt", "w") as f:
            f.write("\n".join(lines))

    @staticmethod
    def list_runs(phase: str = None, strategy: str = None):
        from tabulate import tabulate
        results_dir = Path(config.RESULTS_DIR)
        if not results_dir.exists():
            print("No results yet.")
            return pd.DataFrame()

        rows   = []
        phases = [phase] if phase else PHASES

        for p in phases:
            phase_dir = results_dir / p
            if not phase_dir.exists():
                continue

            for entry in sorted(phase_dir.iterdir()):
                if not entry.is_dir():
                    continue

                summary_direct = entry / "summary.csv"
                if summary_direct.exists():
                    _add_row(rows, p, "legacy", "legacy", entry, summary_direct)
                    continue

                strat_name = entry.name
                for version_dir in sorted(entry.iterdir(), reverse=True):
                    if not version_dir.is_dir():
                        continue
                    version_summary = version_dir / "summary.csv"
                    if version_summary.exists():
                        _add_row(rows, p, strat_name, version_dir.name, version_dir, version_summary)
                        continue
                    for run_dir in sorted(version_dir.iterdir(), reverse=True):
                        if not run_dir.is_dir():
                            continue
                        summary = run_dir / "summary.csv"
                        if summary.exists():
                            _add_row(rows, p, strat_name, version_dir.name, run_dir, summary)

        if not rows:
            print("No completed runs found.")
            return pd.DataFrame()

        runs_df = pd.DataFrame(rows)
        if strategy:
            runs_df = runs_df[runs_df["Strategy"].str.lower() == strategy.lower()]

        title = f"Phase: {phase.upper()}" if phase else "All Phases"
        if strategy:
            title += f" | Strategy: {strategy}"
        print(f"\n📚 Backtest History — {title}")
        print(tabulate(runs_df, headers="keys", tablefmt="rounded_outline",
                       showindex=False, floatfmt=".2f"))
        return runs_df


def _add_row(rows, phase, strategy_name, version_tag, run_dir, summary_path):
    try:
        df   = pd.read_csv(summary_path)
        meta = {}
        meta_path = run_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
        if df.empty:
            return
        best = df.loc[df["Sharpe"].idxmax()] if "Sharpe" in df.columns else df.iloc[0]
        rows.append({
            "Phase":    phase,
            "Strategy": strategy_name,
            "Version":  version_tag,
            "Run":      run_dir.name,
            "Date":     meta.get("timestamp", "?")[:16],
            "Range":    meta.get("date_tag", "full"),
            "RF":       "✅" if meta.get("regime_filter") else "❌",
            "Return %": best.get("Return %", 0),
            "Sharpe":   best.get("Sharpe", 0),
            "Max DD %": best.get("Max DD %", 0),
            "WR %":     best.get("Win Rate %", 0),
            "Trades":   best.get("Trades", 0),
        })
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase",    default=None, choices=PHASES)
    parser.add_argument("--strategy", default=None)
    args = parser.parse_args()
    ResultsManager.list_runs(phase=args.phase, strategy=args.strategy)

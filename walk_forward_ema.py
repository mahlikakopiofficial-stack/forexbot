"""Fixed-parameter walk-forward paper evaluation for the EMA example.

Each fold is a separate virtual-balance simulation. Pre-fold candles warm up the
indicator but cannot open positions. This is a diagnostic, not an optimizer or a
claim of profitability.
"""
import argparse
import json
import math
from functools import partial
from pathlib import Path

import pandas as pd

from backtest import POINT_SIZE, SYMBOL, load_history, run_backtest, validate_history
from ema_strategy import ema_crossover_strategy

METRICS = (
    "starting_balance", "final_balance", "net_pnl_usd", "return_pct",
    "trade_count", "wins", "losses", "win_rate_pct", "profit_factor",
    "max_drawdown_pct", "rejected_entries",
)


def evaluate_walk_forward(
    history,
    *,
    fast=12,
    slow=26,
    folds=5,
    starting_balance=100.0,
    units=50.0,
    point_size=POINT_SIZE,
    slippage_points=1.0,
    commission_per_side=0.0,
    stop_loss_pips=20.0,
    take_profit_pips=40.0,
):
    if isinstance(fast, bool) or isinstance(slow, bool) or int(fast) != fast or int(slow) != slow:
        raise ValueError("EMA periods must be integers")
    fast, slow = int(fast), int(slow)
    if fast < 2 or slow < 3 or fast >= slow:
        raise ValueError("EMA periods must satisfy 2 <= fast < slow")
    if isinstance(folds, bool) or int(folds) != folds or not 2 <= int(folds) <= 20:
        raise ValueError("folds must be an integer between 2 and 20")
    folds = int(folds)

    df = validate_history(history)
    warmup = slow + 2
    active_bars = len(df) - warmup
    bars_per_fold = active_bars // folds
    if bars_per_fold < 3:
        raise ValueError(
            f"Not enough history for {folds} folds with EMA({fast},{slow}); "
            "load more candles or use fewer folds."
        )

    options = {
        "starting_balance": starting_balance,
        "units": units,
        "point_size": point_size,
        "slippage_points": slippage_points,
        "commission_per_side": commission_per_side,
        "stop_loss_pips": stop_loss_pips,
        "take_profit_pips": take_profit_pips,
    }
    strategy = partial(ema_crossover_strategy, fast=fast, slow=slow)
    results = []
    fold_results = []

    for i in range(folds):
        start = warmup + i * bars_per_fold
        end = (warmup + (i + 1) * bars_per_fold) if i < folds - 1 else len(df)
        context_start = max(0, start - warmup)
        context = df.iloc[context_start:end].reset_index(drop=True)
        context_bars = start - context_start

        def fold_strategy(history_so_far, context_bars=context_bars):
            if len(history_so_far) <= context_bars:
                return "HOLD"
            return strategy(history_so_far)

        result = run_backtest(context, strategy=fold_strategy, **options)
        fold_start = df.iloc[start]["time_utc"]
        fold_end = df.iloc[end - 1]["time_utc"]
        early_trades = [
            trade for trade in result["trades"]
            if pd.Timestamp(trade["entry_time"]) < fold_start
        ]
        if early_trades:
            raise RuntimeError(f"Fold {i + 1} opened a position before its test window")

        item = {
            "fold": i + 1,
            "test_candles": end - start,
            "warmup_candles": context_bars,
            "test_start_utc": fold_start.isoformat(),
            "test_end_utc": fold_end.isoformat(),
            "metrics": {key: result[key] for key in METRICS},
            "trade_records": result["trades"],
            "equity_curve": result["equity_curve"],
        }
        results.append(result)
        fold_results.append(item)

    all_trades = [trade for result in results for trade in result["trades"]]
    gross_wins = sum(t["net_pnl_usd"] for t in all_trades if t["net_pnl_usd"] > 0)
    gross_losses = -sum(t["net_pnl_usd"] for t in all_trades if t["net_pnl_usd"] < 0)
    total_trade_count = len(all_trades)
    total_wins = sum(t["net_pnl_usd"] > 0 for t in all_trades)
    total_losses = sum(t["net_pnl_usd"] < 0 for t in all_trades)
    pooled_pf = gross_wins / gross_losses if gross_losses > 0 else None

    summary = {
        "mode": "FIXED_PARAMETER_WALK_FORWARD_PAPER_EVALUATION",
        "live_orders": False,
        "symbol": SYMBOL,
        "timeframe": "M15",
        "strategy": f"EMA({fast},{slow}) crossover",
        "parameters_tuned_on_folds": False,
        "folds": folds,
        "virtual_starting_balance_per_fold": float(starting_balance),
        "mean_fold_return_pct": sum(x["metrics"]["return_pct"] for x in fold_results) / folds,
        "worst_fold_return_pct": min(x["metrics"]["return_pct"] for x in fold_results),
        "best_fold_return_pct": max(x["metrics"]["return_pct"] for x in fold_results),
        "mean_fold_max_drawdown_pct": sum(x["metrics"]["max_drawdown_pct"] for x in fold_results) / folds,
        "worst_fold_max_drawdown_pct": max(x["metrics"]["max_drawdown_pct"] for x in fold_results),
        "total_trades_across_independent_folds": total_trade_count,
        "pooled_wins": int(total_wins),
        "pooled_losses": int(total_losses),
        "pooled_win_rate_pct": (100.0 * total_wins / total_trade_count) if total_trade_count else 0.0,
        "pooled_profit_factor": pooled_pf,
        "fold_results": [
            {key: value for key, value in fold.items() if key not in {"trade_records", "equity_curve"}}
            for fold in fold_results
        ],
        "assumptions": results[0]["assumptions"],
        "limitations": [
            "Each fold is an independent virtual-balance simulation, not one continuous compounded account.",
            "Positions are closed at the end of each fold by the backtester.",
            "Spread is approximated from broker bars, not exact historical ticks.",
            "Parameters are fixed; this script does not search for the best settings.",
            "Results on this historical dataset are exploratory and do not guarantee future performance.",
        ],
    }
    return summary, fold_results


def write_walk_forward(summary, fold_results, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary.json"
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, allow_nan=False)
    paths = {"summary": summary_path}
    for fold in fold_results:
        number = fold["fold"]
        trades_path = out / f"fold_{number}_trades.csv"
        equity_path = out / f"fold_{number}_equity_curve.csv"
        pd.DataFrame(fold["trade_records"]).to_csv(trades_path, index=False)
        pd.DataFrame(fold["equity_curve"]).to_csv(equity_path, index=False)
        paths[f"fold_{number}_trades"] = trades_path
        paths[f"fold_{number}_equity"] = equity_path
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", type=int, default=12)
    parser.add_argument("--slow", type=int, default=26)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--starting-balance", type=float, default=100.0)
    parser.add_argument("--units", type=float, default=50.0)
    parser.add_argument("--slippage-points", type=float, default=1.0)
    parser.add_argument("--commission-per-side", type=float, default=0.0)
    parser.add_argument("--stop-loss-pips", type=float, default=20.0)
    parser.add_argument("--take-profit-pips", type=float, default=40.0)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    if not 2 <= args.fast < args.slow:
        parser.error("EMA periods must satisfy 2 <= fast < slow")
    if not 2 <= args.folds <= 20:
        parser.error("--folds must be between 2 and 20")

    try:
        summary, fold_results = evaluate_walk_forward(
            load_history(),
            fast=args.fast,
            slow=args.slow,
            folds=args.folds,
            starting_balance=args.starting_balance,
            units=args.units,
            slippage_points=args.slippage_points,
            commission_per_side=args.commission_per_side,
            stop_loss_pips=args.stop_loss_pips,
            take_profit_pips=args.take_profit_pips,
        )
        out_dir = args.output_dir or f"reports/ema_walk_forward_{args.fast}_{args.slow}"
        paths = write_walk_forward(summary, fold_results, out_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"WALK-FORWARD EVALUATION FAILED: {exc}")
        return 2

    print("=== FIXED-PARAMETER WALK-FORWARD PAPER EVALUATION ===")
    print(f"Symbol: {summary['symbol']} | Strategy: {summary['strategy']} | Folds: {summary['folds']}")
    for fold in summary["fold_results"]:
        m = fold["metrics"]
        print(
            f"Fold {fold['fold']} [{fold['test_start_utc']} -> {fold['test_end_utc']}]: "
            f"return={m['return_pct']:.3f}% | trades={m['trade_count']} | "
            f"PF={m['profit_factor']} | max DD={m['max_drawdown_pct']:.3f}%"
        )
    print(
        f"Mean fold return={summary['mean_fold_return_pct']:.3f}% | "
        f"Worst fold return={summary['worst_fold_return_pct']:.3f}% | "
        f"Pooled PF={summary['pooled_profit_factor']}"
    )
    print("Reports:", Path(out_dir).resolve())
    print("Independent paper folds only; no broker connection or orders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

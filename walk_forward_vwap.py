"""Walk-forward paper evaluation for the Gold M5 rolling-VWAP strategy."""
import argparse
import json
import os
from pathlib import Path

import pandas as pd

from backtest import POINT_SIZE, load_history, run_backtest, validate_history
from vwap_strategy import DEFAULT_VWAP_PERIOD, vwap_crossover_signals


METRICS = (
    "starting_balance", "final_balance", "net_pnl_usd", "return_pct",
    "trade_count", "wins", "losses", "win_rate_pct", "profit_factor",
    "max_drawdown_pct", "rejected_entries",
)


def evaluate_walk_forward(
    history, *, folds=5, period=DEFAULT_VWAP_PERIOD,
    starting_balance=100.0, units=50.0, point_size=POINT_SIZE,
    slippage_points=1.0, commission_per_side=0.0,
    stop_loss_pips=20.0, take_profit_pips=40.0,
):
    if isinstance(folds, bool) or not isinstance(folds, int) or not 2 <= folds <= 20:
        raise ValueError("folds must be an integer between 2 and 20")
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise ValueError("period must be an integer of at least 2")
    df = validate_history(history)
    signals = vwap_crossover_signals(df, period=period)
    warmup = period
    active = len(df) - warmup
    per_fold = active // folds
    if per_fold < 3:
        raise ValueError("Not enough history for the requested VWAP walk-forward folds")

    options = {
        "starting_balance": starting_balance,
        "units": units,
        "point_size": point_size,
        "slippage_points": slippage_points,
        "commission_per_side": commission_per_side,
        "stop_loss_pips": stop_loss_pips,
        "take_profit_pips": take_profit_pips,
    }
    fold_results = []
    results = []
    for number in range(folds):
        start = warmup + number * per_fold
        end = warmup + (number + 1) * per_fold if number < folds - 1 else len(df)
        context_start = max(0, start - warmup)
        context = df.iloc[context_start:end].reset_index(drop=True)

        def strategy(history_so_far, context_start=context_start, start=start):
            global_index = context_start + len(history_so_far) - 1
            if global_index < start:
                return "HOLD"
            return signals[global_index]

        result = run_backtest(context, strategy=strategy, **options)
        fold_start = df.iloc[start]["time_utc"]
        fold_end = df.iloc[end - 1]["time_utc"]
        early_entries = [t for t in result["trades"] if pd.Timestamp(t["entry_time"]) < fold_start]
        if early_entries:
            raise RuntimeError(f"Fold {number + 1} traded before its test window")

        results.append(result)
        fold_results.append({
            "fold": number + 1,
            "test_candles": end - start,
            "warmup_candles": start - context_start,
            "test_start_utc": fold_start.isoformat(),
            "test_end_utc": fold_end.isoformat(),
            "metrics": {key: result[key] for key in METRICS},
            "trades": result["trades"],
            "equity_curve": result["equity_curve"],
        })

    all_trades = [t for result in results for t in result["trades"]]
    wins = sum(t["net_pnl_usd"] > 0 for t in all_trades)
    gross_wins = sum(t["net_pnl_usd"] for t in all_trades if t["net_pnl_usd"] > 0)
    gross_losses = -sum(t["net_pnl_usd"] for t in all_trades if t["net_pnl_usd"] < 0)
    summary = {
        "mode": "FIXED_RULE_VWAP_WALK_FORWARD_PAPER",
        "live_orders": False,
        "symbol": os.environ.get("FOREX_SYMBOL", "GOLD#").strip(),
        "timeframe": "M5",
        "strategy": f"Rolling VWAP({period}) close-cross; opposite crossing reverses",
        "vwap_period": period,
        "volume_source": "MT5 tick_volume proxy for Gold CFD activity",
        "folds": folds,
        "fold_results": [{key: value for key, value in f.items() if key not in {"trades", "equity_curve"}} for f in fold_results],
        "mean_fold_return_pct": sum(f["metrics"]["return_pct"] for f in fold_results) / folds,
        "worst_fold_return_pct": min(f["metrics"]["return_pct"] for f in fold_results),
        "best_fold_return_pct": max(f["metrics"]["return_pct"] for f in fold_results),
        "mean_fold_max_drawdown_pct": sum(f["metrics"]["max_drawdown_pct"] for f in fold_results) / folds,
        "total_trades": len(all_trades),
        "pooled_profit_factor": gross_wins / gross_losses if gross_losses > 0 else None,
        "pooled_win_rate_pct": 100 * wins / len(all_trades) if all_trades else 0.0,
        "assumptions": results[0]["assumptions"],
        "limitations": [
            "MT5 tick volume is a broker activity proxy, not centralized Gold volume.",
            "Each fold is an independent paper account, not a compounded account.",
            "Historical bar spread and slippage are approximations, not tick-accurate fills.",
            "A positive result is not proof of future profitability.",
        ],
    }
    return summary, fold_results


def write_walk_forward(summary, folds, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary.json"
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, allow_nan=False)
    paths = {"summary": summary_path}
    for fold in folds:
        n = fold["fold"]
        trade_path = out / f"fold_{n}_trades.csv"
        equity_path = out / f"fold_{n}_equity_curve.csv"
        pd.DataFrame(fold["trades"]).to_csv(trade_path, index=False)
        pd.DataFrame(fold["equity_curve"]).to_csv(equity_path, index=False)
        paths[f"fold_{n}_trades"] = trade_path
        paths[f"fold_{n}_equity"] = equity_path
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--period", type=int, default=DEFAULT_VWAP_PERIOD)
    parser.add_argument("--starting-balance", type=float, default=5000.0)
    parser.add_argument("--units", type=float, default=1.0)
    parser.add_argument("--point-size", type=float, default=float(os.environ.get("FOREX_POINT_SIZE", "0.01")))
    parser.add_argument("--slippage-points", type=float, default=1.0)
    parser.add_argument("--commission-per-side", type=float, default=0.0)
    parser.add_argument("--stop-loss-pips", type=float, default=500.0)
    parser.add_argument("--take-profit-pips", type=float, default=1000.0)
    parser.add_argument("--output-dir", default="reports/gold_vwap200_walk_forward_m5")
    args = parser.parse_args()
    if not 2 <= args.folds <= 20:
        parser.error("--folds must be between 2 and 20")
    if args.period < 2:
        parser.error("--period must be at least 2")
    try:
        summary, folds = evaluate_walk_forward(
            load_history(), folds=args.folds, period=args.period,
            starting_balance=args.starting_balance, units=args.units,
            point_size=args.point_size, slippage_points=args.slippage_points,
            commission_per_side=args.commission_per_side,
            stop_loss_pips=args.stop_loss_pips, take_profit_pips=args.take_profit_pips,
        )
        paths = write_walk_forward(summary, folds, args.output_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"VWAP WALK-FORWARD FAILED: {exc}")
        return 2

    print("=== GOLD M5 ROLLING VWAP WALK-FORWARD PAPER EVALUATION ===")
    print(f"Symbol: {summary['symbol']} | VWAP period: {summary['vwap_period']} | folds: {summary['folds']}")
    for fold in summary["fold_results"]:
        m = fold["metrics"]
        print(f"Fold {fold['fold']}: return={m['return_pct']:.3f}% | trades={m['trade_count']} | PF={m['profit_factor']} | max DD={m['max_drawdown_pct']:.3f}%")
    print(f"Mean fold return={summary['mean_fold_return_pct']:.3f}% | worst={summary['worst_fold_return_pct']:.3f}% | pooled PF={summary['pooled_profit_factor']}")
    print("Reports:", Path(args.output_dir).resolve())
    print("Paper simulation only; no broker connection or orders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

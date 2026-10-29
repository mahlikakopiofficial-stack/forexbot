"""Run the same shared EMA crossover rule used by the MT5 demo runner.

This is a historical paper simulation only. It never connects to MT5 or sends
broker orders. The example EMA settings are not performance validated.
"""
import argparse
from functools import partial
from pathlib import Path

from backtest import POINT_SIZE, load_history, run_backtest
from backtest_report import write_report
from ema_strategy import ema_crossover_strategy


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Historical paper backtest for the shared EMA crossover rule"
    )
    parser.add_argument("--fast", type=int, default=12, help="Fast EMA period")
    parser.add_argument("--slow", type=int, default=26, help="Slow EMA period")
    parser.add_argument("--starting-balance", type=float, default=100.0)
    parser.add_argument(
        "--units", type=float, default=50.0,
        help="EUR base-currency units per position; simulation uses no leverage",
    )
    parser.add_argument("--point-size", type=float, default=POINT_SIZE)
    parser.add_argument("--slippage-points", type=float, default=1.0)
    parser.add_argument("--commission-per-side", type=float, default=0.0)
    parser.add_argument(
        "--stop-loss-pips", type=float, default=20.0,
        help="Illustrative broker-side stop distance, matched to demo runner",
    )
    parser.add_argument(
        "--take-profit-pips", type=float, default=40.0,
        help="Illustrative broker-side target distance, matched to demo runner",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Report directory; defaults to reports/ema_FAST_SLOW",
    )
    args = parser.parse_args()

    if args.fast < 2 or args.slow < 3 or args.fast >= args.slow:
        parser.error("EMA periods must satisfy 2 <= fast < slow and fast < slow")

    try:
        history = load_history()
        strategy = partial(
            ema_crossover_strategy, fast=args.fast, slow=args.slow
        )
        result = run_backtest(
            history=history,
            strategy=strategy,
            starting_balance=args.starting_balance,
            units=args.units,
            point_size=args.point_size,
            slippage_points=args.slippage_points,
            commission_per_side=args.commission_per_side,
            stop_loss_pips=args.stop_loss_pips,
            take_profit_pips=args.take_profit_pips,
        )
    except (OSError, ValueError) as exc:
        print(f"BACKTEST FAILED: {exc}")
        return 2

    result["strategy_rules"] = (
        f"EMA({args.fast},{args.slow}) crossover on completed closes; "
        "signal fills on the next candle open; "
        f"stop-loss={args.stop_loss_pips} pips; "
        f"take-profit={args.take_profit_pips} pips."
    )
    output_dir = args.output_dir or f"reports/ema_{args.fast}_{args.slow}"
    paths = write_report(result, output_dir=output_dir)

    print("=== HISTORICAL PAPER BACKTEST ===")
    print("Mode: paper simulation; no broker orders")
    print("Strategy:", result["strategy_rules"])
    print("Candles:", len(history))
    print("First candle UTC:", history["time_utc"].iloc[0].isoformat())
    print("Last candle UTC:", history["time_utc"].iloc[-1].isoformat())
    print(f"Starting balance: {result['starting_balance']:.2f}")
    print(f"Final balance: {result['final_balance']:.2f}")
    print(f"Net P&L: {result['net_pnl_usd']:.4f}")
    print(f"Return: {result['return_pct']:.3f}%")
    print("Trades:", result["trade_count"])
    print("Wins / losses:", result["wins"], "/", result["losses"])
    print(f"Win rate: {result['win_rate_pct']:.2f}%")
    print("Profit factor:", result["profit_factor"])
    print(f"Maximum drawdown: {result['max_drawdown_pct']:.3f}%")
    print("Entries rejected by 1:1 exposure limit:", result["rejected_entries"])
    print("Assumptions:", result["assumptions"])
    print("Reports:")
    for name, path in paths.items():
        print(f"  {name}: {Path(path).resolve()}")
    print(
        "IMPORTANT: historical performance is not a guarantee; this model "
        "does not reproduce exact tick, spread, slippage or broker execution."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

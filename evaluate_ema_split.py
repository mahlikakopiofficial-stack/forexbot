"""Compare fixed EMA settings on chronological train and holdout periods.

Paper simulation only. This is an exploratory split, not a profit guarantee.
"""
import argparse
import json
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


def evaluate(history, fast=12, slow=26, train_fraction=0.70):
    if not 2 <= fast < slow:
        raise ValueError("EMA periods must satisfy 2 <= fast < slow")
    if not 0.5 <= train_fraction <= 0.9:
        raise ValueError("train_fraction must be between 0.5 and 0.9")
    df = validate_history(history)
    split = int(len(df) * train_fraction)
    warmup = slow + 2
    if split <= warmup or len(df) - split < warmup:
        raise ValueError("Not enough candles for train and holdout periods")

    train = df.iloc[:split].reset_index(drop=True)
    holdout = df.iloc[split - warmup:].reset_index(drop=True)
    holdout_start = df.iloc[split]["time_utc"]

    train_strategy = partial(ema_crossover_strategy, fast=fast, slow=slow)

    def holdout_strategy(history_so_far):
        if len(history_so_far) < warmup:
            return "HOLD"
        return ema_crossover_strategy(history_so_far, fast=fast, slow=slow)

    options = {
        "starting_balance": 100.0,
        "units": 50.0,
        "point_size": POINT_SIZE,
        "slippage_points": 1.0,
        "commission_per_side": 0.0,
        "stop_loss_pips": 20.0,
        "take_profit_pips": 40.0,
    }
    train_result = run_backtest(train, train_strategy, **options)
    holdout_result = run_backtest(holdout, holdout_strategy, **options)
    if any(pd.Timestamp(t["entry_time"]) < holdout_start for t in holdout_result["trades"]):
        raise RuntimeError("Holdout opened a position before its start")

    summary = {
        "mode": "CHRONOLOGICAL_PAPER_EVALUATION",
        "live_orders": False,
        "symbol": SYMBOL,
        "timeframe": "M15",
        "strategy": f"EMA({fast},{slow}) crossover",
        "parameters_tuned_on_holdout": False,
        "split": {
            "train_candles": len(train),
            "holdout_candles": len(df) - split,
            "warmup_candles_not_traded": warmup,
            "train_first_candle_utc": df.iloc[0]["time_utc"].isoformat(),
            "train_last_candle_utc": df.iloc[split - 1]["time_utc"].isoformat(),
            "holdout_first_candle_utc": holdout_start.isoformat(),
            "holdout_last_candle_utc": df.iloc[-1]["time_utc"].isoformat(),
        },
        "train": {k: train_result[k] for k in METRICS},
        "holdout": {k: holdout_result[k] for k in METRICS},
        "assumptions": train_result["assumptions"],
        "limitations": [
            "One chronological split is exploratory, not proof of a durable edge.",
            "Do not tune EMA settings against the holdout results.",
            "Spread is approximated from broker bar data, not historical tick data.",
            "Train and holdout simulations each start with the same virtual balance.",
        ],
    }
    return summary, train_result, holdout_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", type=int, default=12)
    parser.add_argument("--slow", type=int, default=26)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    if not 2 <= args.fast < args.slow:
        parser.error("EMA periods must satisfy 2 <= fast < slow")
    if not 0.5 <= args.train_fraction <= 0.9:
        parser.error("--train-fraction must be between 0.5 and 0.9")

    try:
        summary, train, holdout = evaluate(
            load_history(), args.fast, args.slow, args.train_fraction
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"EVALUATION FAILED: {exc}")
        return 2

    out = Path(args.output_dir or f"reports/ema_split_{args.fast}_{args.slow}")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, allow_nan=False)
    for label, result in (("train", train), ("holdout", holdout)):
        pd.DataFrame(result["trades"]).to_csv(out / f"{label}_trades.csv", index=False)
        pd.DataFrame(result["equity_curve"]).to_csv(out / f"{label}_equity_curve.csv", index=False)

    print("=== CHRONOLOGICAL PAPER EVALUATION ===")
    print(f"Symbol: {summary['symbol']} | Strategy: {summary['strategy']}")
    print("Train:", summary["split"]["train_candles"], "candles")
    print("Holdout:", summary["split"]["holdout_candles"], "candles")
    for label in ("train", "holdout"):
        m = summary[label]
        print(f"{label.upper()}: return={m['return_pct']:.3f}% | P&L={m['net_pnl_usd']:.4f} | trades={m['trade_count']} | PF={m['profit_factor']} | max DD={m['max_drawdown_pct']:.3f}%")
    print("Reports:", out.resolve())
    print("Paper evaluation only; results do not guarantee future performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

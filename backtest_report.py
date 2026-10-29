import json
from pathlib import Path

import pandas as pd


SUMMARY_FIELDS = [
    "starting_balance",
    "final_balance",
    "net_pnl_usd",
    "return_pct",
    "trade_count",
    "wins",
    "losses",
    "win_rate_pct",
    "profit_factor",
    "max_drawdown_pct",
    "rejected_entries",
]


def write_report(result, output_dir="reports"):
    """Save a backtest result without changing the source database."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    missing = [key for key in SUMMARY_FIELDS if key not in result]
    if missing:
        raise ValueError(f"Missing report fields: {missing}")

    summary = {
        key: result[key]
        for key in SUMMARY_FIELDS
    }

    summary["mode"] = "PAPER_BACKTEST"
    summary["live_orders"] = False
    summary["strategy_rules"] = result.get("strategy_rules", "Supplied by caller")
    summary["assumptions"] = result.get("assumptions", {})

    summary_path = output_dir / "summary.json"
    trades_path = output_dir / "trades.csv"
    equity_path = output_dir / "equity_curve.csv"

    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, allow_nan=False)

    trade_columns = [
        "side",
        "units",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "mid_pnl_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "commission_usd",
        "net_pnl_usd",
        "reason",
    ]

    trades = pd.DataFrame(
        result.get("trades", []),
        columns=trade_columns,
    )
    trades.to_csv(trades_path, index=False)

    equity = pd.DataFrame(
        result.get("equity_curve", []),
        columns=["time_utc", "equity"],
    )
    equity.to_csv(equity_path, index=False)

    print("Paper backtest report saved:")
    print("Summary:", summary_path.resolve())
    print("Trades:", trades_path.resolve())
    print("Equity curve:", equity_path.resolve())
    print("Live orders: disabled")

    return {
        "summary": summary_path,
        "trades": trades_path,
        "equity_curve": equity_path,
    }

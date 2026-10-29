import json

import pandas as pd
import pytest

from backtest_report import write_report


def test_report_creates_three_files(tmp_path):
    result = {
        "starting_balance": 100.0,
        "final_balance": 100.5,
        "net_pnl_usd": 0.5,
        "return_pct": 0.5,
        "trade_count": 1,
        "wins": 1,
        "losses": 0,
        "win_rate_pct": 100.0,
        "profit_factor": None,
        "max_drawdown_pct": 0.0,
        "rejected_entries": 0,
        "strategy_rules": "EMA(3,8) test rule",
        "trades": [{
            "side": "BUY",
            "units": 50.0,
            "entry_time": pd.Timestamp(
                "2026-01-01T00:15:00Z"
            ),
            "exit_time": pd.Timestamp(
                "2026-01-01T00:30:00Z"
            ),
            "entry_price": 1.1,
            "exit_price": 1.11,
            "mid_pnl_usd": 0.5,
            "spread_cost_usd": 0.0,
            "slippage_cost_usd": 0.0,
            "commission_usd": 0.0,
            "net_pnl_usd": 0.5,
            "reason": "EXIT_SIGNAL",
        }],
        "equity_curve": [{
            "time_utc": pd.Timestamp(
                "2026-01-01T00:15:00Z"
            ),
            "equity": 100.5,
        }],
    }

    paths = write_report(result, tmp_path)

    assert all(path.exists() for path in paths.values())

    with paths["summary"].open(encoding="utf-8") as file:
        summary = json.load(file)

    assert summary["final_balance"] == pytest.approx(100.5)
    assert summary["live_orders"] is False
    assert summary["strategy_rules"] == "EMA(3,8) test rule"

    trades = pd.read_csv(paths["trades"])
    assert len(trades) == 1
    assert trades.iloc[0]["side"] == "BUY"

    equity = pd.read_csv(paths["equity_curve"])
    assert len(equity) == 1
    assert equity.iloc[0]["equity"] == pytest.approx(100.5)


def test_report_rejects_missing_fields(tmp_path):
    with pytest.raises(ValueError, match="Missing report fields"):
        write_report({}, tmp_path)
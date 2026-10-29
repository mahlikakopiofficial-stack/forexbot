import numpy as np
import pandas as pd
import pytest

from backtest import run_backtest
from ema_strategy import ema_crossover_signal, ema_crossover_strategy


def test_ema_signal_returns_hold_until_enough_completed_prices():
    assert ema_crossover_signal([1.1, 1.1001], fast=2, slow=4) == "HOLD"


def test_ema_signal_validates_periods_and_closes():
    with pytest.raises(ValueError, match="satisfy"):
        ema_crossover_signal([1.1] * 20, fast=8, slow=8)
    with pytest.raises(ValueError, match="invalid close"):
        ema_crossover_signal(
            [1.1, 1.2, float("nan"), 1.3, 1.4, 1.5],
            fast=2, slow=3,
        )


def test_dataframe_strategy_matches_signal_function():
    history = pd.DataFrame({
        "close": [10, 9, 8, 7, 6, 7, 8],
    })
    assert ema_crossover_strategy(history, fast=2, slow=4) == (
        ema_crossover_signal(history["close"], fast=2, slow=4)
    )


def test_ema_backtest_uses_prefix_only_and_produces_summary():
    close = (
        [1.105 - 0.0001 * i for i in range(25)]
        + [1.102 + 0.0001 * i for i in range(45)]
        + [1.1064 - 0.0001 * i for i in range(30)]
    )
    opens = [close[0], *close[:-1]]
    data = pd.DataFrame({
        "time_utc": pd.date_range(
            "2026-01-01T00:00:00Z", periods=len(close), freq="15min"
        ),
        "open": opens,
        "high": [max(o, c) + 0.00005 for o, c in zip(opens, close)],
        "low": [min(o, c) - 0.00005 for o, c in zip(opens, close)],
        "close": close,
        "spread": [10] * len(close),
    })
    seen_lengths = []

    def strategy(history):
        seen_lengths.append(len(history))
        return ema_crossover_strategy(history, fast=3, slow=8)

    result = run_backtest(
        data,
        strategy=strategy,
        starting_balance=100.0,
        units=50.0,
        point_size=0.00001,
        slippage_points=0,
        commission_per_side=0,
    )

    assert seen_lengths == list(range(1, len(data)))
    assert result["trade_count"] >= 1
    assert result["assumptions"]["price_basis"] == "bid"
    assert result["assumptions"]["leverage_used"] is False
    assert all(np.isfinite(t["net_pnl_usd"]) for t in result["trades"])

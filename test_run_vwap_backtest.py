import math

import pandas as pd
import pytest

from backtest import run_backtest
from run_vwap_backtest import make_vwap_strategy
from vwap_strategy import vwap_crossover_signals


def synthetic_history(rows=20):
    times = pd.date_range("2026-10-28T08:00:00Z", periods=rows, freq="5min")
    pattern = [1.100, 1.099, 1.098, 1.102, 1.103, 1.097, 1.096, 1.104, 1.105, 1.095]
    closes = (pattern * ((rows + len(pattern) - 1) // len(pattern)))[:rows]
    opens = [closes[0], *closes[:-1]]
    return pd.DataFrame({
        "time_utc": times,
        "open": opens,
        "high": [max(opens[i], closes[i]) + 0.00010 for i in range(rows)],
        "low": [min(opens[i], closes[i]) - 0.00010 for i in range(rows)],
        "close": closes,
        "spread": [10.0] * rows,
        "tick_volume": [100] * rows,
    })


def test_strategy_callback_is_causal_and_aligns_to_history_prefix():
    data = synthetic_history()
    strategy = make_vwap_strategy(data)
    signals = vwap_crossover_signals(data)
    for length in range(1, len(data) + 1):
        assert strategy(data.iloc[:length]) == signals[length - 1]
    assert strategy(data.iloc[:3]) != "BUY"


def test_vwap_paper_backtest_can_take_long_and_short_sides():
    data = synthetic_history(250)
    strategy = make_vwap_strategy(data)
    result = run_backtest(
        data, strategy=strategy, starting_balance=1000, units=50,
        slippage_points=0, commission_per_side=0,
        stop_loss_pips=None, take_profit_pips=None,
    )
    sides = {trade["side"] for trade in result["trades"]}
    assert "BUY" in sides
    assert "SELL" in sides
    assert result["assumptions"]["leverage_used"] is False

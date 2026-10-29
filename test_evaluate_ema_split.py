import math

import pandas as pd
import pytest

from evaluate_ema_split import evaluate


def synthetic_history(rows=120):
    times = pd.date_range("2026-01-01T00:00:00Z", periods=rows, freq="15min")
    closes = [1.10 + 0.001 * math.sin(index * 0.35) for index in range(rows)]
    opens = [closes[0], *closes[:-1]]
    return pd.DataFrame({
        "time_utc": times,
        "open": opens,
        "high": [max(opens[i], closes[i]) + 0.00015 for i in range(rows)],
        "low": [min(opens[i], closes[i]) - 0.00015 for i in range(rows)],
        "close": closes,
        "spread": [10.0] * rows,
        "tick_volume": [100] * rows,
    })


def test_holdout_has_no_entries_before_split_and_no_live_orders():
    history = synthetic_history()
    summary, train, holdout = evaluate(history, fast=3, slow=8, train_fraction=0.70)
    split_index = int(len(history) * 0.70)
    holdout_start = history.iloc[split_index]["time_utc"]

    assert summary["mode"] == "CHRONOLOGICAL_PAPER_EVALUATION"
    assert summary["live_orders"] is False
    assert summary["split"]["train_candles"] == split_index
    assert summary["split"]["holdout_candles"] == len(history) - split_index
    assert summary["parameters_tuned_on_holdout"] is False
    assert all(pd.Timestamp(t["entry_time"]) >= holdout_start for t in holdout["trades"])
    assert train["starting_balance"] == pytest.approx(100.0)
    assert holdout["starting_balance"] == pytest.approx(100.0)


def test_split_rejects_insufficient_history():
    with pytest.raises(ValueError, match="Not enough candles"):
        evaluate(synthetic_history(20), fast=3, slow=8)


@pytest.mark.parametrize("fraction", [float("nan"), 0.49, 0.91])
def test_split_rejects_invalid_fraction(fraction):
    with pytest.raises(ValueError, match="train_fraction"):
        evaluate(synthetic_history(), train_fraction=fraction)


def test_split_rejects_invalid_ema_periods():
    with pytest.raises(ValueError, match="EMA periods"):
        evaluate(synthetic_history(), fast=8, slow=3)

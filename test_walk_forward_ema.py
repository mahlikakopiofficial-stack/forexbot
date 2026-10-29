import math

import pandas as pd
import pytest

from walk_forward_ema import evaluate_walk_forward, write_walk_forward


def synthetic_history(rows=180):
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


def test_walk_forward_folds_only_trade_inside_each_test_window():
    history = synthetic_history()
    summary, folds = evaluate_walk_forward(
        history, fast=3, slow=8, folds=5
    )

    assert summary["mode"] == "FIXED_PARAMETER_WALK_FORWARD_PAPER_EVALUATION"
    assert summary["live_orders"] is False
    assert summary["parameters_tuned_on_folds"] is False
    assert len(folds) == 5

    for fold in folds:
        start = pd.Timestamp(fold["test_start_utc"])
        assert all(pd.Timestamp(t["entry_time"]) >= start
                   for t in fold["trade_records"])
        assert fold["test_candles"] >= 3
        assert fold["metrics"]["starting_balance"] == pytest.approx(100.0)


@pytest.mark.parametrize("folds", [1, 21, 2.5, True])
def test_walk_forward_rejects_invalid_fold_count(folds):
    with pytest.raises(ValueError, match="folds"):
        evaluate_walk_forward(synthetic_history(), folds=folds)


def test_walk_forward_requires_enough_history():
    with pytest.raises(ValueError, match="Not enough history"):
        evaluate_walk_forward(synthetic_history(30), fast=12, slow=26, folds=5)


def test_walk_forward_writes_reproducible_reports(tmp_path):
    summary, folds = evaluate_walk_forward(
        synthetic_history(), fast=3, slow=8, folds=3
    )
    paths = write_walk_forward(summary, folds, tmp_path)

    assert paths["summary"].is_file()
    assert all(paths[f"fold_{i}_trades"].is_file() for i in range(1, 4))
    assert all(paths[f"fold_{i}_equity"].is_file() for i in range(1, 4))

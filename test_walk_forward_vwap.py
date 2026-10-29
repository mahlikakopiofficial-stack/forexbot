import math

import pandas as pd
import pytest

from walk_forward_vwap import evaluate_walk_forward, write_walk_forward


def synthetic_history(rows=240):
    times = pd.date_range("2026-10-20T08:00:00Z", periods=rows, freq="5min")
    closes = [1.10 + 0.001 * math.sin(index * 0.45) for index in range(rows)]
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


def test_vwap_walk_forward_never_opens_before_test_window():
    summary, folds = evaluate_walk_forward(synthetic_history(), folds=4)
    assert summary["live_orders"] is False
    assert summary["mode"] == "FIXED_RULE_VWAP_WALK_FORWARD_PAPER"
    assert len(folds) == 4
    for fold in folds:
        start = pd.Timestamp(fold["test_start_utc"])
        assert all(pd.Timestamp(t["entry_time"]) >= start for t in fold["trades"])
        assert fold["metrics"]["starting_balance"] == pytest.approx(100.0)


@pytest.mark.parametrize("folds", [1, 21, 2.5, True])
def test_vwap_walk_forward_rejects_invalid_fold_count(folds):
    with pytest.raises(ValueError, match="folds"):
        evaluate_walk_forward(synthetic_history(), folds=folds)


def test_vwap_walk_forward_writes_reports(tmp_path):
    summary, folds = evaluate_walk_forward(synthetic_history(), folds=3)
    paths = write_walk_forward(summary, folds, tmp_path)
    assert paths["summary"].is_file()
    assert all(paths[f"fold_{i}_trades"].is_file() for i in range(1, 4))

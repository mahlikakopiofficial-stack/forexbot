import pandas as pd
import pytest

from vwap_strategy import (
    DEFAULT_VWAP_PERIOD,
    rolling_vwap,
    vwap_crossover_signal,
    vwap_crossover_signals,
)


def history(closes, times=None, volumes=None):
    if times is None:
        times = pd.date_range(
            "2026-10-28T22:00:00Z", periods=len(closes), freq="5min"
        )
    if volumes is None:
        volumes = [100] * len(closes)
    return pd.DataFrame({
        "time_utc": times,
        "high": closes,
        "low": closes,
        "close": closes,
        "tick_volume": volumes,
    })


def test_default_period_is_200():
    assert DEFAULT_VWAP_PERIOD == 200


def test_cross_above_rolling_vwap_generates_buy():
    data = history([1.0] * 200 + [1.1])
    assert vwap_crossover_signal(data) == "BUY"


def test_cross_below_rolling_vwap_generates_sell():
    data = history([1.0] * 200 + [0.9])
    assert vwap_crossover_signal(data) == "SELL"


def test_no_cross_returns_hold():
    data = history([1.0] * 205)
    assert vwap_crossover_signal(data) == "HOLD"


def test_warmup_requires_full_rolling_window_and_previous_value():
    short_data = history([1.0] * 199)
    assert vwap_crossover_signals(short_data) == ["HOLD"] * 199

    one_window = history([1.0] * 200)
    assert vwap_crossover_signal(one_window) == "HOLD"


def test_tick_volume_weights_rolling_vwap():
    data = history(
        [1.0, 2.0, 3.0, 5.0],
        volumes=[1, 1, 2, 4],
    )
    result = rolling_vwap(data, period=3)
    assert result.iloc[1] != result.iloc[0]  # the first valid point is not ready yet
    assert result.iloc[2] == pytest.approx((1.0 + 2.0 + 6.0) / 4.0)
    assert result.iloc[3] == pytest.approx((2.0 + 6.0 + 20.0) / 7.0)


def test_invalid_or_missing_volume_is_rejected():
    data = history([1.1, 1.2])
    data.loc[1, "tick_volume"] = -1
    with pytest.raises(ValueError, match="tick_volume"):
        rolling_vwap(data, period=2)
    with pytest.raises(ValueError, match="missing"):
        rolling_vwap(data.drop(columns=["tick_volume"]), period=2)


@pytest.mark.parametrize("period", [0, 1, True, 2.5, "200"])
def test_invalid_vwap_period_is_rejected(period):
    with pytest.raises(ValueError, match="period"):
        rolling_vwap(history([1.0, 1.1]), period=period)


def test_signal_function_uses_only_supplied_completed_candles():
    data = history([1.0] * 200 + [1.1])
    assert vwap_crossover_signal(data.iloc[:-1]) == "HOLD"
    assert vwap_crossover_signal(data) == "BUY"

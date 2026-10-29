import pandas as pd
import pytest

from vwap_strategy import session_vwap, vwap_crossover_signal, vwap_crossover_signals


def history(closes, times=None, volumes=None):
    if times is None:
        times = pd.date_range("2026-10-28T22:00:00Z", periods=len(closes), freq="15min")
    if volumes is None:
        volumes = [100] * len(closes)
    return pd.DataFrame({
        "time_utc": times,
        "high": closes,
        "low": closes,
        "close": closes,
        "tick_volume": volumes,
    })


def test_cross_above_vwap_generates_buy():
    data = history([1.100, 1.099, 1.098, 1.102])
    assert vwap_crossover_signal(data) == "BUY"


def test_cross_below_vwap_generates_sell():
    data = history([1.100, 1.101, 1.102, 1.098])
    assert vwap_crossover_signal(data) == "SELL"


def test_no_cross_returns_hold():
    data = history([1.100, 1.099, 1.098, 1.097])
    assert vwap_crossover_signal(data) == "HOLD"


def test_vwap_resets_at_broker_local_day_and_does_not_cross_between_days():
    times = pd.to_datetime([
        "2026-10-28T20:45:00Z",
        "2026-10-28T21:00:00Z",
    ], utc=True)
    data = history([1.100, 1.105], times=times)
    assert vwap_crossover_signals(data) == ["HOLD", "HOLD"]


def test_tick_volume_weights_vwap():
    data = history([1.0, 2.0], times=pd.date_range("2026-10-28T10:00:00Z", periods=2, freq="15min"), volumes=[1, 3])
    result = session_vwap(data)
    assert result.iloc[0] == pytest.approx(1.0)
    assert result.iloc[1] == pytest.approx(1.75)


def test_invalid_or_missing_volume_is_rejected():
    data = history([1.1, 1.2])
    data.loc[1, "tick_volume"] = -1
    with pytest.raises(ValueError, match="tick_volume"):
        session_vwap(data)
    with pytest.raises(ValueError, match="missing"):
        session_vwap(data.drop(columns=["tick_volume"]))


def test_signal_function_uses_only_supplied_completed_candles():
    data = history([1.100, 1.099, 1.098, 1.102])
    full_signal = vwap_crossover_signal(data)
    prefix_signal = vwap_crossover_signal(data.iloc[:-1])
    assert prefix_signal != "BUY"
    assert full_signal == "BUY"

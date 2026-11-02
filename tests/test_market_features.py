import pandas as pd
import pytest

from research.market_features import add_market_features


def sample_history(n=80):
    times = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    close = [100 + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "time_utc": times,
        "open": [x - 0.03 for x in close],
        "high": [x + 0.08 for x in close],
        "low": [x - 0.08 for x in close],
        "close": close,
    })


def test_features_include_expected_columns():
    result = add_market_features(sample_history())
    expected = {
        "ema_59", "atr", "swing_high_confirmed", "swing_low_confirmed",
        "bos_up_close", "bos_down_close", "fvg_up_gap", "fvg_down_gap",
        "bullish_engulfing", "bearish_engulfing", "small_body",
        "long_lower_wick", "long_upper_wick",
    }
    assert expected.issubset(result.columns)
    assert result["ema_59"].notna().any()
    assert result["atr"].notna().any()


def test_swing_confirmation_is_delayed_until_right_bars_pass():
    data = sample_history(20)
    data.loc[10, "high"] = 110.0
    data.loc[11, "high"] = 105.0
    data.loc[12, "high"] = 104.0
    result = add_market_features(data, swing_left=2, swing_right=2)
    assert pd.isna(result.loc[10, "swing_high_confirmed"])
    assert result.loc[12, "swing_high_confirmed"] == 110.0


def test_rejects_duplicate_timestamps():
    data = sample_history(10)
    data.loc[9, "time_utc"] = data.loc[8, "time_utc"]
    with pytest.raises(ValueError, match="unique and chronological"):
        add_market_features(data)


def test_rejects_invalid_ohlc():
    data = sample_history(10)
    data.loc[4, "high"] = data.loc[4, "low"] - 1
    with pytest.raises(ValueError, match="Invalid OHLC"):
        add_market_features(data)

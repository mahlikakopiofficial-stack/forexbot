"""Rolling VWAP(200) cross signals for M5 Gold candles.

Spot gold CFDs do not expose centralized exchange volume through MT5. This
implementation weights typical price by broker tick volume as an approximation.
Signals use completed candles only; execution belongs on the next candle.
"""
from __future__ import annotations

import math

import pandas as pd


REQUIRED_COLUMNS = {"time_utc", "high", "low", "close", "tick_volume"}
DEFAULT_VWAP_PERIOD = 200


def rolling_vwap(history: pd.DataFrame, period: int = DEFAULT_VWAP_PERIOD) -> pd.Series:
    """Return a rolling HLC3 VWAP weighted by MT5 tick volume."""
    if not isinstance(history, pd.DataFrame):
        raise ValueError("VWAP history must be a pandas DataFrame")
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise ValueError("VWAP period must be an integer greater than or equal to 2")

    missing = REQUIRED_COLUMNS - set(history.columns)
    if missing:
        raise ValueError(f"VWAP history missing columns: {sorted(missing)}")

    df = history.reset_index(drop=True).copy()
    times = pd.to_datetime(df["time_utc"], utc=True, errors="raise")
    if times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError("VWAP timestamps must be unique and chronological")

    prices = {}
    for name in ("high", "low", "close"):
        prices[name] = pd.to_numeric(df[name], errors="raise").astype("float64")
        if not prices[name].map(lambda value: math.isfinite(value) and value > 0).all():
            raise ValueError(f"VWAP {name} prices must be positive and finite")

    volume = pd.to_numeric(df["tick_volume"], errors="raise").astype("float64")
    if not volume.map(lambda value: math.isfinite(value) and value >= 0).all():
        raise ValueError("VWAP tick_volume must be finite and nonnegative")

    if (prices["high"] < prices["low"]).any():
        raise ValueError("VWAP high cannot be below low")
    if (
        (prices["high"] < prices["close"]).any()
        or (prices["low"] > prices["close"]).any()
    ):
        raise ValueError("VWAP OHLC relationships are invalid")

    typical_price = (prices["high"] + prices["low"] + prices["close"]) / 3.0
    weighted_price = typical_price * volume
    numerator = weighted_price.rolling(window=period, min_periods=period).sum()
    denominator = volume.rolling(window=period, min_periods=period).sum()
    return numerator.div(denominator.where(denominator > 0))


def vwap_crossover_signals(
    history: pd.DataFrame,
    period: int = DEFAULT_VWAP_PERIOD,
) -> list[str]:
    """Return one signal per completed candle: BUY, SELL, or HOLD."""
    df = history.reset_index(drop=True)
    vwap = rolling_vwap(df, period=period)
    close = pd.to_numeric(df["close"], errors="raise").astype("float64")

    signals = ["HOLD"] * len(df)
    for i in range(1, len(df)):
        previous_vwap = vwap.iloc[i - 1]
        current_vwap = vwap.iloc[i]
        if pd.isna(previous_vwap) or pd.isna(current_vwap):
            continue

        previous_delta = float(close.iloc[i - 1] - previous_vwap)
        current_delta = float(close.iloc[i] - current_vwap)
        if previous_delta <= 0 and current_delta > 0:
            signals[i] = "BUY"
        elif previous_delta >= 0 and current_delta < 0:
            signals[i] = "SELL"
    return signals


def vwap_crossover_signal(
    history: pd.DataFrame,
    period: int = DEFAULT_VWAP_PERIOD,
) -> str:
    """Return the signal for the latest completed candle in history."""
    signals = vwap_crossover_signals(history, period=period)
    return signals[-1] if signals else "HOLD"

"""Daily session VWAP cross signals for M15 Forex candles.

Spot FX has no single centralized traded-volume tape. The VWAP here is
weighted by the MT5 broker's tick_volume and is an approximation. Signals use
completed closes only; execution belongs on the next candle.
"""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import pandas as pd


REQUIRED_COLUMNS = {"time_utc", "high", "low", "close", "tick_volume"}


def session_vwap(
    history: pd.DataFrame,
    session_timezone: str = "Europe/Athens",
) -> pd.Series:
    """Calculate cumulative HLC3 * tick-volume VWAP, reset each broker-local day."""
    if not isinstance(history, pd.DataFrame):
        raise ValueError("VWAP history must be a pandas DataFrame")
    missing = REQUIRED_COLUMNS - set(history.columns)
    if missing:
        raise ValueError(f"VWAP history missing columns: {sorted(missing)}")
    try:
        ZoneInfo(session_timezone)
    except Exception as exc:
        raise ValueError(f"Invalid session timezone: {session_timezone!r}") from exc

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
    session_ids = times.dt.tz_convert(session_timezone).dt.strftime("%Y-%m-%d")
    weighted_price = typical_price * volume
    cumulative_value = weighted_price.groupby(session_ids, sort=False).cumsum()
    cumulative_volume = volume.groupby(session_ids, sort=False).cumsum()
    return cumulative_value.div(cumulative_volume.where(cumulative_volume > 0))


def vwap_crossover_signals(
    history: pd.DataFrame,
    session_timezone: str = "Europe/Athens",
) -> list[str]:
    """Return one signal per completed candle: BUY, SELL, or HOLD."""
    if "close" not in history.columns:
        raise ValueError("VWAP history must contain close")
    df = history.reset_index(drop=True)
    vwap = session_vwap(df, session_timezone=session_timezone)
    close = pd.to_numeric(df["close"], errors="raise").astype("float64")
    times = pd.to_datetime(df["time_utc"], utc=True, errors="raise")
    session_ids = times.dt.tz_convert(session_timezone).dt.strftime("%Y-%m-%d")

    signals = ["HOLD"] * len(df)
    for i in range(1, len(df)):
        if session_ids.iloc[i] != session_ids.iloc[i - 1]:
            continue
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
    session_timezone: str = "Europe/Athens",
) -> str:
    """Return the signal for the latest completed candle in history."""
    signals = vwap_crossover_signals(history, session_timezone)
    return signals[-1] if signals else "HOLD"

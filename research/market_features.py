"""Descriptive OHLC feature extraction for historical market research.

The output is deliberately non-actionable: it labels observations such as EMA,
ATR, confirmed swing points, BOS-style closes, FVG-style gaps, and candle
shapes. It does not generate entries, exits, forecasts, or broker orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"time_utc", "open", "high", "low", "close"}


def _validate_ohlc(history: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(history.columns)
    if missing:
        raise ValueError(f"Missing OHLC columns: {sorted(missing)}")
    df = history.copy().reset_index(drop=True)
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, errors="raise")
    if df["time_utc"].duplicated().any() or not df["time_utc"].is_monotonic_increasing:
        raise ValueError("Timestamps must be unique and chronological")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="raise").astype("float64")
        if not np.isfinite(df[col]).all() or (df[col] <= 0).any():
            raise ValueError(f"{col} must contain positive finite prices")
    valid = (
        (df["low"] <= df[["open", "close"]].min(axis=1))
        & (df["high"] >= df[["open", "close"]].max(axis=1))
        & (df["low"] <= df["high"])
    )
    if not valid.all():
        raise ValueError("Invalid OHLC relationships")
    return df


def add_market_features(
    history: pd.DataFrame,
    ema_period: int = 59,
    atr_period: int = 14,
    swing_left: int = 3,
    swing_right: int = 3,
) -> pd.DataFrame:
    """Return descriptive features without look-ahead in swing confirmation.

    Swing levels are emitted on the bar where the pivot becomes confirmable
    (after swing_right later bars), not retroactively on the pivot bar.
    BOS-style labels mean a close crossed a previously confirmed swing level.
    Three-candle FVG-style labels are geometric gaps, not evidence of orders
    or institutional activity.
    """
    for name, value in {
        "ema_period": ema_period,
        "atr_period": atr_period,
        "swing_left": swing_left,
        "swing_right": swing_right,
    }.items():
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    df = _validate_ohlc(history)
    close = df["close"]
    prev_close = close.shift(1)

    df["ema_59"] = close.ewm(span=ema_period, adjust=False, min_periods=ema_period).mean()

    prev_close_for_range = prev_close.fillna(df["close"])
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close_for_range).abs(),
            (df["low"] - prev_close_for_range).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = true_range.ewm(
        alpha=1.0 / atr_period, adjust=False, min_periods=atr_period
    ).mean()

    n = len(df)
    swing_high_confirmed = np.full(n, np.nan)
    swing_low_confirmed = np.full(n, np.nan)
    bos_up = np.zeros(n, dtype=bool)
    bos_down = np.zeros(n, dtype=bool)
    last_high = np.nan
    last_low = np.nan

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = close.to_numpy()
    previous_closes = prev_close.to_numpy()

    for i in range(swing_left + swing_right, n):
        pivot = i - swing_right
        left = pivot - swing_left
        right = pivot + swing_right + 1

        candidate_high = highs[pivot]
        candidate_low = lows[pivot]

        if candidate_high == np.max(highs[left:right]) and np.count_nonzero(
            highs[left:right] == candidate_high
        ) == 1:
            last_high = candidate_high
            swing_high_confirmed[i] = candidate_high

        if candidate_low == np.min(lows[left:right]) and np.count_nonzero(
            lows[left:right] == candidate_low
        ) == 1:
            last_low = candidate_low
            swing_low_confirmed[i] = candidate_low

        if np.isfinite(last_high) and np.isfinite(previous_closes[i]):
            bos_up[i] = previous_closes[i] <= last_high < closes[i]
        if np.isfinite(last_low) and np.isfinite(previous_closes[i]):
            bos_down[i] = previous_closes[i] >= last_low > closes[i]

    df["swing_high_confirmed"] = swing_high_confirmed
    df["swing_low_confirmed"] = swing_low_confirmed
    df["bos_up_close"] = bos_up
    df["bos_down_close"] = bos_down

    df["fvg_up_gap"] = np.nan
    df["fvg_down_gap"] = np.nan
    if n >= 3:
        up_gap = df["low"] - df["high"].shift(2)
        down_gap = df["low"].shift(2) - df["high"]
        df.loc[up_gap > 0, "fvg_up_gap"] = up_gap[up_gap > 0]
        df.loc[down_gap > 0, "fvg_down_gap"] = down_gap[down_gap > 0]

    body = (df["close"] - df["open"]).abs()
    candle_range = (df["high"] - df["low"]).replace(0, np.nan)
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    previous_open = df["open"].shift(1)
    previous_close = df["close"].shift(1)

    df["bullish_engulfing"] = (
        (df["close"] > df["open"])
        & (previous_close < previous_open)
        & (df["open"] <= previous_close)
        & (df["close"] >= previous_open)
    ).fillna(False)
    df["bearish_engulfing"] = (
        (df["close"] < df["open"])
        & (previous_close > previous_open)
        & (df["open"] >= previous_close)
        & (df["close"] <= previous_open)
    ).fillna(False)
    df["small_body"] = (body / candle_range <= 0.1).fillna(False)
    df["long_lower_wick"] = (
        (lower_wick >= 2.0 * body) & (lower_wick / candle_range >= 0.5)
    ).fillna(False)
    df["long_upper_wick"] = (
        (upper_wick >= 2.0 * body) & (upper_wick / candle_range >= 0.5)
    ).fillna(False)

    return df

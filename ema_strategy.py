"""Shared, closed-candle EMA crossover signal rules.

This is an educational integration strategy. It is not performance-validated and
must not be interpreted as a recommendation or guarantee of results.
"""
import math

import pandas as pd


def ema_crossover_signal(closes, fast: int = 12, slow: int = 26) -> str:
    """Return BUY, SELL or HOLD; only the supplied completed closes are used."""
    if isinstance(fast, bool) or isinstance(slow, bool):
        raise ValueError("EMA periods must be integers")
    try:
        fast_value = int(fast)
        slow_value = int(slow)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("EMA periods must be integers") from exc
    if fast_value != fast or slow_value != slow:
        raise ValueError("EMA periods must be integers")
    if fast_value < 2 or slow_value < 3 or fast_value >= slow_value:
        raise ValueError("EMA periods must satisfy 2 <= fast < slow and slow >= 3")

    series = pd.Series(list(closes), dtype="float64")
    if not series.map(
        lambda value: math.isfinite(float(value)) and float(value) > 0
    ).all():
        raise ValueError("EMA input contains invalid close prices")
    if len(series) < slow_value + 2:
        return "HOLD"

    fast_line = series.ewm(span=fast_value, adjust=False).mean()
    slow_line = series.ewm(span=slow_value, adjust=False).mean()
    previous = float(fast_line.iloc[-2] - slow_line.iloc[-2])
    current = float(fast_line.iloc[-1] - slow_line.iloc[-1])

    if previous <= 0 and current > 0:
        return "BUY"
    if previous >= 0 and current < 0:
        return "SELL"
    return "HOLD"


def ema_crossover_strategy(history, fast: int = 12, slow: int = 26) -> str:
    """Backtester-compatible adapter: history contains no future candles."""
    if "close" not in history.columns:
        raise ValueError("Strategy history must contain a close column")
    return ema_crossover_signal(history["close"], fast=fast, slow=slow)

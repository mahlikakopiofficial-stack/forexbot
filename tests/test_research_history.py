from datetime import datetime, timezone

import pytest

from sync_research_history import utc_text, validate_rate


def test_mt5_epoch_is_stored_as_utc():
    epoch = int(datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc).timestamp())
    assert utc_text(epoch) == "2026-11-02T08:00:00Z"


def test_validate_rate_keeps_symbol_and_timeframe():
    rate = {
        "time": 1793606400,
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "tick_volume": 123,
        "spread": 8,
        "real_volume": 0,
    }
    row = validate_rate(rate, "EURUSD#", "M5")
    assert row[0] == "EURUSD#"
    assert row[1] == "M5"
    assert row[3:7] == (1.1, 1.2, 1.0, 1.15)


def test_validate_rate_rejects_invalid_ohlc():
    rate = {
        "time": 1793606400,
        "open": 1.1,
        "high": 1.05,
        "low": 1.0,
        "close": 1.15,
        "tick_volume": 123,
        "spread": 8,
        "real_volume": 0,
    }
    with pytest.raises(ValueError, match="invalid OHLC"):
        validate_rate(rate, "EURUSD#", "M5")

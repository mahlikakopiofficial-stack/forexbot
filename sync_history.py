import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"

MT5_PATH = os.environ.get(
    "MT5_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)

SYMBOL = os.environ.get("FOREX_SYMBOL", "GOLD#").strip()
TIMEFRAME_NAME = "M5"
TIMEFRAME = mt5.TIMEFRAME_M5
# About 20,000 M5 candles provides several weeks of Gold price history.
# Override locally with FOREX_HISTORY_BARS if the MT5 terminal has fewer bars available.
HISTORY_COUNT = int(os.environ.get("FOREX_HISTORY_BARS", "20000"))

# Observed XM server schedule: GMT+2 in winter, GMT+3 in summer.
SERVER_TZ = ZoneInfo("Europe/Athens")


def to_utc(raw_timestamp):
    # Interpret the returned numeric timestamp as a broker-clock label.
    encoded = datetime.fromtimestamp(
        float(raw_timestamp),
        tz=timezone.utc,
    )
    wall_time = encoded.replace(tzinfo=None)

    first = wall_time.replace(tzinfo=SERVER_TZ, fold=0)
    second = wall_time.replace(tzinfo=SERVER_TZ, fold=1)

    if first.utcoffset() != second.utcoffset():
        raise ValueError(
            f"Ambiguous server timestamp: {wall_time}"
        )

    converted = first.astimezone(timezone.utc)

    round_trip = (
        converted.astimezone(SERVER_TZ)
        .replace(tzinfo=None)
    )

    if round_trip != wall_time:
        raise ValueError(
            f"Invalid server-local timestamp: {wall_time}"
        )

    return converted


def main():
    if not 100 <= HISTORY_COUNT <= 100000:
        raise SystemExit(
            "FOREX_HISTORY_BARS must be an integer between 100 and 100000"
        )

    if not DB_FILE.is_file():
        raise SystemExit(f"Database not found: {DB_FILE}")

    if not Path(MT5_PATH).is_file():
        raise SystemExit(f"MT5 terminal not found: {MT5_PATH}")

    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        raise SystemExit(
            f"MT5 initialization failed: {mt5.last_error()}"
        )

    try:
        terminal = mt5.terminal_info()

        if terminal is None or not terminal.connected:
            raise RuntimeError("MT5 terminal is disconnected")

        if not mt5.symbol_select(SYMBOL, True):
            raise RuntimeError(
                f"Could not select {SYMBOL}: {mt5.last_error()}"
            )

        print("Source: copy_rates_from_pos only")
        print("Broker:", (
            mt5.account_info().server
            if mt5.account_info() else "unavailable"
        ))

        rates = mt5.copy_rates_from_pos(
            SYMBOL,
            TIMEFRAME,
            1,  # Exclude the forming candle.
            HISTORY_COUNT,
        )

        if rates is None or len(rates) == 0:
            raise RuntimeError(
                f"No candles returned: {mt5.last_error()}"
            )

    finally:
        mt5.shutdown()

    rows = []

    for rate in sorted(rates, key=lambda item: int(item["time"])):
        timestamp = to_utc(rate["time"])

        prices = [
            float(rate[name])
            for name in ("open", "high", "low", "close")
        ]

        if not all(math.isfinite(p) and p > 0 for p in prices):
            raise ValueError(f"Invalid prices at {timestamp}")

        open_price, high, low, close = prices

        if (
            low > min(open_price, close)
            or high < max(open_price, close)
            or low > high
        ):
            raise ValueError(f"Invalid OHLC at {timestamp}")

        time_text = (
            timestamp.isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        rows.append((
            SYMBOL,
            TIMEFRAME_NAME,
            time_text,
            open_price,
            high,
            low,
            close,
            int(rate["tick_volume"]),
            int(rate["spread"]),
            int(rate["real_volume"]),
        ))

    timestamps = [row[2] for row in rows]

    if len(timestamps) != len(set(timestamps)):
        raise ValueError(
            "Duplicate timestamps found after conversion. "
            "No database writes were made."
        )

    if timestamps != sorted(timestamps):
        raise ValueError(
            "Converted candles are not chronological. "
            "No database writes were made."
        )

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        existing_rows = conn.execute("""
            SELECT time_utc, open, high, low, close
            FROM market_candles
            WHERE symbol = ? AND timeframe = ?
        """, (SYMBOL, TIMEFRAME_NAME)).fetchall()

        existing = {row[0]: row[1:] for row in existing_rows}

        # Refuse to silently overwrite conflicting existing candles.
        for row in rows:
            previous = existing.get(row[2])

            if previous is not None:
                if any(
                    abs(float(old) - float(new)) > 1e-8
                    for old, new in zip(previous, row[3:7])
                ):
                    raise ValueError(
                        f"Existing candle conflicts at {row[2]}. "
                        "No additional candles were inserted."
                    )

        before = len(existing_rows)

        conn.executemany("""
            INSERT OR IGNORE INTO market_candles (
                symbol, timeframe, time_utc,
                open, high, low, close,
                tick_volume, spread, real_volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

        after = conn.execute("""
            SELECT COUNT(*)
            FROM market_candles
            WHERE symbol = ? AND timeframe = ?
        """, (SYMBOL, TIMEFRAME_NAME)).fetchone()[0]

        conn.commit()

    print("\nHistory sync successful.")
    print("Candles requested:", HISTORY_COUNT)
    print("Candles returned:", len(rows))
    print("New candles inserted:", after - before)
    print("Total candles in database:", after)
    print("First UTC candle:", timestamps[0])
    print("Latest UTC candle:", timestamps[-1])
    print("Virtual account was not modified.")

    if len(rows) < HISTORY_COUNT:
        print(
            "\nNOTE: MT5 returned fewer candles than requested. "
            "Historical availability may be limited by the terminal's "
            "chart-history setting."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5

MT5_PATH = os.environ.get(
    "MT5_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)

SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_M15
SERVER_TZ = ZoneInfo("Europe/Athens")


def to_server_adjusted_utc(raw_timestamp):
    # Diagnostic hypothesis only: interpret the raw timestamp's
    # displayed clock as XM server-local time.
    encoded = datetime.fromtimestamp(
        float(raw_timestamp),
        tz=timezone.utc,
    )
    wall_time = encoded.replace(tzinfo=None)
    local_time = wall_time.replace(tzinfo=SERVER_TZ)

    return local_time.astimezone(timezone.utc)


def show_rate(label, rate):
    raw_time = int(rate["time"])
    raw_utc = datetime.fromtimestamp(
        raw_time, tz=timezone.utc
    )
    adjusted = to_server_adjusted_utc(raw_time)

    ohlc = tuple(
        round(float(rate[name]), 8)
        for name in ("open", "high", "low", "close")
    )

    print(
        f"{label} raw_as_UTC={raw_utc.isoformat()} "
        f"adjusted={adjusted.isoformat()} OHLC={ohlc}"
    )


def signature(rate):
    return tuple(
        round(float(rate[name]), 8)
        for name in ("open", "high", "low", "close")
    ) + (
        int(rate["tick_volume"]),
        int(rate["spread"]),
    )


def main():
    if not Path(MT5_PATH).is_file():
        raise SystemExit(f"MT5 terminal not found: {MT5_PATH}")

    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        raise SystemExit(f"MT5 initialization failed: {mt5.last_error()}")

    try:
        now = datetime.now(timezone.utc)

        print("=== MT5 TIME DIAGNOSTIC ===")
        print("Computer UTC:", now.isoformat())
        print("Python package:", mt5.__version__)
        print("MT5 terminal version:", mt5.version())

        terminal = mt5.terminal_info()
        print(
            "Terminal connected:",
            bool(terminal and terminal.connected),
        )

        account = mt5.account_info()
        print(
            "Broker server:",
            account.server if account else "unavailable",
        )

        if not mt5.symbol_select(SYMBOL, True):
            raise RuntimeError(
                f"Cannot select {SYMBOL}: {mt5.last_error()}"
            )

        tick = mt5.symbol_info_tick(SYMBOL)

        if tick is None:
            raise RuntimeError(f"No live tick: {mt5.last_error()}")

        raw_tick = datetime.fromtimestamp(
            tick.time_msc / 1000,
            tz=timezone.utc,
        )
        adjusted_tick = to_server_adjusted_utc(
            tick.time_msc / 1000
        )

        print("\n=== LIVE TICK ===")
        print("Raw timestamp interpreted as UTC:", raw_tick.isoformat())
        print(
            "Raw age (seconds):",
            round((now - raw_tick).total_seconds(), 2),
        )
        print("Server-adjusted timestamp:", adjusted_tick.isoformat())
        print(
            "Adjusted age (seconds):",
            round((now - adjusted_tick).total_seconds(), 2),
        )
        print("Bid:", tick.bid, "Ask:", tick.ask)

        positional = mt5.copy_rates_from_pos(
            SYMBOL, TIMEFRAME, 0, 8
        )

        if positional is None or len(positional) == 0:
            raise RuntimeError(
                f"Positional candle request failed: {mt5.last_error()}"
            )

        print("\n=== LAST FIVE POSITIONAL CANDLES ===")
        for rate in positional[-5:]:
            show_rate("POSITION", rate)

        # Use explicit UTC-aware datetimes as required by the
        # documented API convention.
        utc_from = now - timedelta(hours=8)
        utc_to = now

        ranged = mt5.copy_rates_range(
            SYMBOL, TIMEFRAME, utc_from, utc_to
        )

        if ranged is None or len(ranged) == 0:
            print("\nRange query returned no candles:", mt5.last_error())
            return 2

        print("\n=== LAST FIVE DATE-RANGE CANDLES ===")
        for rate in ranged[-5:]:
            show_rate("RANGE", rate)

        range_signatures = {signature(rate) for rate in ranged}
        matches = [
            rate for rate in positional
            if signature(rate) in range_signatures
        ]

        print("\n=== COMPARISON ===")
        print("Positional candles returned:", len(positional))
        print("Date-range candles returned:", len(ranged))
        print(
            "Matching OHLC/volume signatures:",
            len(matches),
            "of",
            len(positional),
        )

        print(
            "\nNo timestamps or database records were changed."
        )
        print(
            "Compare raw and adjusted times; do not assume "
            "either conversion is correct before reviewing the output."
        )

        return 0

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
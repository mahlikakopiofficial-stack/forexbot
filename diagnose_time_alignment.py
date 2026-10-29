import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

MT5_PATH = os.environ.get(
    "MT5_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)

SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_M15
OBSERVED_OFFSET = timedelta(hours=2)


def signature(rate):
    return (
        round(float(rate["open"]), 8),
        round(float(rate["high"]), 8),
        round(float(rate["low"]), 8),
        round(float(rate["close"]), 8),
        int(rate["tick_volume"]),
        int(rate["spread"]),
    )


def show(label, rates, limit=4):
    print(f"\n{label}: {0 if rates is None else len(rates)} bars")

    if rates is None:
        print("MT5 error:", mt5.last_error())
        return

    for rate in rates[-limit:]:
        raw_time = datetime.fromtimestamp(
            int(rate["time"]),
            tz=timezone.utc,
        )
        print(
            raw_time.isoformat(),
            "OHLC=",
            tuple(
                round(float(rate[name]), 8)
                for name in ("open", "high", "low", "close")
            ),
        )


def main():
    if not Path(MT5_PATH).is_file():
        raise SystemExit(f"Terminal not found: {MT5_PATH}")

    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        raise SystemExit(f"MT5 initialization failed: {mt5.last_error()}")

    try:
        now = datetime.now(timezone.utc)
        print("Computer UTC:", now.isoformat())
        print("Broker:", (
            mt5.account_info().server
            if mt5.account_info() else "unavailable"
        ))

        # Exclude the current, still-forming M15 candle.
        positional = mt5.copy_rates_from_pos(
            SYMBOL, TIMEFRAME, 1, 12
        )

        if positional is None or len(positional) == 0:
            raise RuntimeError(
                f"No positional bars: {mt5.last_error()}"
            )

        utc_rates = mt5.copy_rates_range(
            SYMBOL,
            TIMEFRAME,
            now - timedelta(hours=8),
            now,
        )

        shifted_rates = mt5.copy_rates_range(
            SYMBOL,
            TIMEFRAME,
            now - timedelta(hours=8) + OBSERVED_OFFSET,
            now + OBSERVED_OFFSET,
        )

        show("Completed positional bars", positional)
        show("UTC range query", utc_rates)
        show("Range shifted by observed offset", shifted_rates)

        pos_signatures = {signature(row) for row in positional}

        utc_signatures = (
            {signature(row) for row in utc_rates}
            if utc_rates is not None else set()
        )
        shifted_signatures = (
            {signature(row) for row in shifted_rates}
            if shifted_rates is not None else set()
        )

        print("\n=== MATCHING COMPLETED BARS ===")
        print(
            "UTC range matches:",
            len(pos_signatures & utc_signatures),
            "of", len(pos_signatures),
        )
        print(
            "Shifted range matches:",
            len(pos_signatures & shifted_signatures),
            "of", len(pos_signatures),
        )

        print("\nDiagnostic only: no data or database was changed.")

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5


def main():
    path = os.environ.get(
        "MT5_PATH",
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
    )

    print("Windows timezone names:", time.tzname)
    print("Computer local time:", datetime.now().astimezone().isoformat())
    print("Computer UTC:", datetime.now(timezone.utc).isoformat())

    if not mt5.initialize(path=path, timeout=15000):
        print("MT5 connection error:", mt5.last_error())
        return

    try:
        print("MT5 version:", mt5.version())

        terminal = mt5.terminal_info()
        print("Terminal connected:", terminal.connected if terminal else None)

        # Print only the broker server name, never account credentials.
        account = mt5.account_info()
        print("Broker server:", account.server if account else "Unavailable")

        symbol = "EURUSD"
        tick = mt5.symbol_info_tick(symbol)

        if tick is not None:
            print("\nLatest tick raw seconds:", tick.time)
            print("Latest tick raw milliseconds:", tick.time_msc)
            print(
                "Tick interpreted as UTC:",
                datetime.fromtimestamp(
                    tick.time_msc / 1000,
                    tz=timezone.utc,
                ).isoformat(),
            )

        rates = mt5.copy_rates_from_pos(
            symbol, mt5.TIMEFRAME_M15, 0, 3
        )

        if rates is not None:
            print("\nLast three raw candle timestamps:")
            for rate in rates:
                print(
                    int(rate["time"]),
                    datetime.fromtimestamp(
                        int(rate["time"]), tz=timezone.utc
                    ).isoformat(),
                    "close =", float(rate["close"]),
                )
        else:
            print("Candle retrieval error:", mt5.last_error())

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
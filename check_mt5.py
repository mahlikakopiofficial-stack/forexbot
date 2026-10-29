import os
from datetime import datetime, timezone

import MetaTrader5 as mt5


def main():
    terminal_path = os.environ.get("MT5_PATH", "").strip()

    if not terminal_path:
        print("ERROR: MT5 terminal path was not detected.")
        return 1

    print(f"Connecting to terminal: {terminal_path}", flush=True)

    try:
        connected = mt5.initialize(
            path=terminal_path,
            timeout=15000,
        )

        if not connected:
            print("MT5 initialization failed:", mt5.last_error())
            return 2

        print("MT5 Python connection: SUCCESS")
        print("MT5 version:", mt5.version())

        terminal = mt5.terminal_info()

        if terminal is None:
            print("Terminal status unavailable:", mt5.last_error())
            return 3

        print("Terminal connected:", terminal.connected)
        print("Terminal path:", terminal.path)

        symbol = os.environ.get("FOREX_SYMBOL", "GOLD#").strip()
        info = mt5.symbol_info(symbol)

        if info is None:
            print(f"{symbol} not found under that exact symbol name.")
            matches = tuple(mt5.symbols_get("*GOLD*") or ()) + tuple(mt5.symbols_get("*XAUUSD*") or ())

            print("Available Gold symbols:")
            for item in matches[:20]:
                print(" -", item.name)

            return 4

        if not info.visible and not mt5.symbol_select(symbol, True):
            print("Could not select EURUSD:", mt5.last_error())
            return 5

        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            print("No tick available:", mt5.last_error())
            return 6

        print("Symbol:", symbol)
        print("Bid:", tick.bid)
        print("Ask:", tick.ask)
        print(
            "Last tick UTC:",
            datetime.fromtimestamp(
                tick.time, tz=timezone.utc
            ).isoformat(),
        )

        print("Read-only data check completed.")
        return 0

    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}")
        return 10

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
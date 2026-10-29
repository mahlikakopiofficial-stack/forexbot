import os
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd


def main():
    terminal_path = os.environ.get(
        "MT5_PATH",
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
    )

    if not Path(terminal_path).is_file():
        print("MT5 terminal executable not found:", terminal_path)
        return 1

    print("Computer UTC time:", datetime.now(timezone.utc).isoformat())

    if not mt5.initialize(path=terminal_path, timeout=15000):
        print("MT5 initialization failed:", mt5.last_error())
        return 2

    try:
        symbol = os.environ.get("FOREX_SYMBOL", "EURUSD").strip()

        if not mt5.symbol_select(symbol, True):
            print("Could not select symbol:", mt5.last_error())
            return 3

        # Position 0 is the current, potentially incomplete candle.
        # Start at position 1 to download completed candles only.
        rates = mt5.copy_rates_from_pos(
            symbol,
            mt5.TIMEFRAME_M15,
            1,
            500,
        )

        if rates is None or len(rates) == 0:
            print("No historical candles returned:", mt5.last_error())
            return 4

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        output_dir = Path("data")
        output_dir.mkdir(parents=True, exist_ok=True)

        symbol_slug = symbol.lower().replace("#", "_")
        output_file = output_dir / f"{symbol_slug}_m15.csv"
        df.to_csv(output_file, index=False)

        print("\nHistorical data downloaded successfully.")
        print("Candles:", len(df))
        print("First candle UTC:", df["time"].iloc[0].isoformat())
        print("Last completed candle UTC:", df["time"].iloc[-1].isoformat())
        print("CSV file:", output_file.resolve())

        tick = mt5.symbol_info_tick(symbol)

        if tick is not None:
            tick_time = datetime.fromtimestamp(
                tick.time_msc / 1000,
                tz=timezone.utc,
            )
            now_utc = datetime.now(timezone.utc)
            age_seconds = (now_utc - tick_time).total_seconds()

            print("\nLatest tick UTC:", tick_time.isoformat())
            print("Tick age in seconds:", round(age_seconds, 1))

            if age_seconds < -60:
                print(
                    "WARNING: Tick timestamp is more than one minute "
                    "in the future relative to this computer's UTC clock."
                )
            elif age_seconds > 300:
                print(
                    "WARNING: Tick is over five minutes old. "
                    "Check market hours and whether quotes are updating."
                )

        print("\nMost recent five completed candles:")
        print(
            df[["time", "open", "high", "low", "close", "spread"]]
            .tail(5)
            .to_string(index=False)
        )

        return 0

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
from pathlib import Path

import pandas as pd

SOURCE = Path("data/eurusd_m15.csv")
OUTPUT = Path("data/eurusd_m15_utc_corrected.csv")

# XM's documented seasonal server schedule.
# Europe/Athens follows the same standard-time/DST offsets.
SERVER_TIMEZONE = "Europe/Athens"


def main():
    if not SOURCE.exists():
        print("Historical CSV not found:", SOURCE)
        return 1

    df = pd.read_csv(SOURCE)

    if "time" not in df.columns:
        print("CSV has no time column.")
        return 1

    # The original CSV labelled observed broker-clock times as UTC.
    # Preserve the displayed clock values before reinterpreting them.
    parsed = pd.to_datetime(df["time"], utc=True, errors="raise")
    server_wall_time = parsed.dt.tz_localize(None)

    try:
        localized = server_wall_time.dt.tz_localize(
            SERVER_TIMEZONE,
            ambiguous="raise",
            nonexistent="raise",
        )
    except Exception as exc:
        print("Timestamp conversion stopped safely.")
        print("Some timestamps may be ambiguous at the DST transition.")
        print(type(exc).__name__, str(exc))
        print("Original CSV remains unchanged.")
        return 2

    df["time"] = (
        localized.dt.tz_convert("UTC")
        .map(lambda value: value.isoformat())
    )

    df.to_csv(OUTPUT, index=False)

    print("Corrected CSV saved:", OUTPUT.resolve())
    print("Candles:", len(df))
    print("First corrected candle:", df["time"].iloc[0])
    print("Last corrected candle:", df["time"].iloc[-1])
    print("\nMost recent five candles:")
    print(df[["time", "open", "high", "low", "close"]].tail().to_string(
        index=False
    ))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
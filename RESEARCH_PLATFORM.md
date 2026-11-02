# Multi-Asset Historical Research Platform

This work is isolated on the institutional-research branch. The existing
M15 VWAP runner and the separate EMA-BAND repository are not changed.

## Scope

- Instruments: broker-specific Gold, EURUSD and GBPUSD symbols.
- Observation timeframes: M5 and H1, stored and analysed independently.
- Descriptive features: EMA(59), ATR, confirmed swing points, BOS-style close
  classifications, three-candle FVG-style geometric gaps and basic candle-shape
  labels.
- Research only: no buy/sell recommendations, forecasts, entries, exits,
  position sizing, or broker order placement.

## Research discipline

1. Preserve the existing SQLite database and add data by symbol/timeframe.
2. Record the exact broker symbol, timezone conversion and candle source.
3. Use only completed candles for historical feature calculations.
4. Confirm swing points only after the configured right-hand bars have closed.
5. Keep H1 and M5 feature calculations independent.
6. Separate descriptive feature generation from statistical evaluation.
7. Use chronological train/validation/holdout partitions; never randomly
   shuffle time-series observations.
8. Include spread, commissions and slippage when reporting historical results.
9. Report sample size, missing data, market regime and uncertainty alongside
   every statistic.
10. Do not interpret FVG or BOS labels as proof of institutional orders.

## Current implementation

research/market_features.py provides read-only feature extraction. It accepts
an OHLC DataFrame with a UTC time_utc column. EMA and ATR periods default to
59 and 14. Swing confirmation defaults to three bars on each side.

The function returns the input columns plus descriptive feature columns. It
does not connect to MT5, access credentials, write to the database, or submit
orders.

## Not yet complete

- Multi-symbol MT5 history discovery and synchronization.
- H1/M5 database audit and coverage report.
- Broker-specific symbol mapping for Gold and GBPUSD.
- Feature tests against real broker history.
- Dashboard and research reports.

The local Windows environment and SQLite database must be tested when the
computer is available. No claim is made that any feature predicts returns or
produces profitability.

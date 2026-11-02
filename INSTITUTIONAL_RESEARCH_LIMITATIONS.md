# Institutional-Style Market Research: Data Limits and Validation

This branch is a descriptive research lab. It does not produce trading signals,
entry/exit rules, position sizing, or broker orders.

## What "institutional" means in practice

There is no single institutional strategy or public indicator recipe. Different
banks, asset managers, market makers and proprietary firms have different
mandates, data access, execution venues and risk controls. Public chart patterns
such as BOS, FVG, engulfing candles and moving averages are descriptive
conventions; they do not reveal who traded, why they traded, or where hidden
orders sit.

Research should distinguish observable facts from interpretations.

## Important FX and CFD data limitations

- Spot FX is an over-the-counter, fragmented market rather than one central
  exchange order book. A retail broker's quotes and tick-volume series are not
  a consolidated view of global trading.
- MT5 tick volume generally counts quote updates for that broker feed. It is
  not the same thing as executed contracts or global spot-FX volume.
- Gold offered by a broker may be a cash CFD or another derivative. Its bars,
  spread, trading hours and contract specifications are not interchangeable
  with exchange-traded COMEX Gold futures.
- A chart-based FVG is a price-gap geometry across candles. It is not proof of
  an institutional order imbalance or an unfilled institutional order.
- A BOS label is only as reliable as the swing definition and confirmation
  delay. Pivots must not be marked before the later bars needed to confirm them.
- OHLC bars cannot reconstruct queue position, individual trades, bid/ask
  depth, intrabar order, or exact stop/target execution.

The BIS describes FX as a decentralised OTC market with many venues and
substantial internalisation. Its research also discusses the role of
cross-asset information and electronic execution. See:
- https://www.bis.org/publications/working-paper-1094-foreign-exchange-market
- https://www.bis.org/publications/qr-202512/fx-trade-execution-landscape-through-prism-2025-bis-triennial-survey

## Data-quality checklist for this project

For each exact broker symbol and timeframe, retain:

1. UTC candle open time and source/broker identity.
2. Bid and ask where available; otherwise record which price basis OHLC uses.
3. Spread observations, not only a single average.
4. Tick volume clearly labelled as broker-feed activity, not traded volume.
5. Symbol contract metadata: digits, point, tick size/value, contract size,
   minimum volume, volume step, trading sessions and quote currency.
6. Missing-bar and duplicate-bar audits, including daylight-saving transitions.
7. Separate M5 and H1 datasets; never merge timeframes or symbols implicitly.
8. Versioned raw data and feature definitions so results can be reproduced.

## Descriptive feature catalogue

The current `research/market_features.py` may label EMA(59), ATR, confirmed
swing highs/lows, BOS-style closes, three-candle FVG geometry and candle shapes.
These are research annotations only. Keep the confirmation time explicit and
avoid look-ahead bias.

Useful non-predictive diagnostics include:
- spread distributions by symbol, session and volatility bucket;
- realised range and ATR distributions;
- missing-data rates and quote staleness;
- feature frequency and persistence by symbol/timeframe;
- stability of descriptive statistics across chronological periods;
- differences between broker feeds for the same instrument.

## Validation principles

- Preserve raw observations; derive features in a separate layer.
- Use chronological splits and walk-forward descriptive reports.
- Include spread, commissions, swaps, slippage and contract-specific costs
  when studying historical outcomes.
- Avoid tuning many definitions against the same sample and then treating the
  best result as independent evidence.
- Report uncertainty, sample size, regime dependence and data limitations.
- Do not interpret a profitable historical interval as proof of a repeatable
  edge or a forecast.

## Scope boundary

This branch is for data integrity, descriptive analytics and educational
historical research only. It is not a recommendation to trade and must not be
used to automate real-money trading.

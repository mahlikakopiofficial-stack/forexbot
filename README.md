# Gold M5 VWAP(200) MT5 Demo Bot

This project is configured for **one asset only: Gold**. The active signal is a
rolling **VWAP(200)** on completed **M5** candles, using MT5 tick volume as a
proxy for activity. XM commonly lists Gold as `GOLD`, while account variants
may show a suffix such as `GOLD#` or a micro variant. Set `FOREX_SYMBOL` to the
exact Gold symbol shown in your MT5 Market Watch. The runner allowlist accepts
only Gold aliases and does not trade EURUSD or other assets.

## Strategy

- **BUY:** the completed M5 close crosses from at/below rolling VWAP(200) to above it.
- **SELL:** the completed M5 close crosses from at/above rolling VWAP(200) to below it.
- Signals are evaluated once per completed candle.
- If the bot's own Gold position exists, an opposite signal closes it and attempts the reverse side, subject to risk limits.
- VWAP is a rolling, volume-weighted average of HLC3 over the latest 200 candles. MT5 tick volume is a proxy; it is not centralized exchange volume.

## Demo-only protections

The executor refuses any account not confirmed by MT5 as **DEMO** on the expected
server `XMGlobal-MT5 2`. There is no live-account order mode in this project.
Order submission defaults off and requires the explicit token
`MT5_DEMO_ORDER_ENABLED=YES_DEMO_ONLY`. Keep this guard enabled.

Provisional demo defaults: 0.01 lot, Gold SL distance 5.00 quoted price units,
TP distance 10.00 quoted price units, no more than 3 new entries per UTC day,
and a $25 daily-equity-loss block. These are integration-test defaults, not
optimized risk settings or a profit claim. Confirm the broker's Gold symbol
digits, minimum stop distance, spread and contract specifications in MT5 before
placing demo orders. A position created previously on EURUSD is not managed
by the Gold bot; reconcile or close it manually in the demo terminal.

A stale candle/quote, account mismatch, unsupported symbol, unresolved order
state or protective-order check failure halts the runner. Never restart after
an uncertain order state until you reconcile it in MT5.

## Install and update

Use the project virtual environment from PowerShell. Do not use a system-wide
Python installation for these commands.

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pytest -q
```

## Read-only symbol check

Open MT5 and connect to the intended demo account. The diagnostic lists Gold
symbol candidates and shows tick, digits, point, minimum lot, spread and stop
level. It never submits orders.

```powershell
$env:FOREX_SYMBOL = "GOLD#"
.\.venv\Scripts\python.exe .\diagnose_mt5_symbol.py
```

If the diagnostic shows a different exact Gold symbol (for example `GOLD`),
set `FOREX_SYMBOL` to that exact name in the same PowerShell session before
continuing. Do not assume a suffix from another account.

## Sync and evaluate M5 history

The existing database is preserved. This sync writes Gold M5 bars into M5
timeframe rows; it does not delete or overwrite old M15/EURUSD history. Set
`FOREX_POINT_SIZE` to the broker-reported `point` for the selected Gold
symbol before interpreting historical costs.

```powershell
$env:FOREX_SYMBOL = "GOLD#"
$env:FOREX_HISTORY_BARS = "20000"
$env:FOREX_POINT_SIZE = "0.01"
.\.venv\Scripts\python.exe .\sync_history.py
.\.venv\Scripts\python.exe .\backtest.py audit
.\.venv\Scripts\python.exe .\run_vwap_backtest.py
.\.venv\Scripts\python.exe .\walk_forward_vwap.py --folds 5
```

The paper backtests model one ounce of Gold with an unleveraged $5,000 virtual
balance by default. This is an approximation of contract sizing, spread and
fills. Review trades, drawdown and fold consistency. The prior session VWAP
setup had negative historical results; the rolling VWAP(200) setup must be
evaluated separately and is not assumed profitable.

## Start a demo cycle

Stop any existing runner with Ctrl+C before switching configurations. Confirm
any previous EURUSD demo position is reconciled or closed manually, because
the Gold-only runner will not manage EURUSD. Use the exact Gold symbol from
the read-only diagnostic:

```powershell
$env:FOREX_SYMBOL = "GOLD#"
$env:MT5_DEMO_SERVER = "XMGlobal-MT5 2"
$env:MT5_DEMO_ORDER_ENABLED = "YES_DEMO_ONLY"
.\.venv\Scripts\python.exe .\mt5_demo_executor.py preflight
.\.venv\Scripts\python.exe .\demo_runner.py --once
```

If preflight passes and a completed candle creates a crossover, the one-shot
runner could place a demo order. A `NO_SIGNAL` result is normal when the
VWAP(200) doesn't cross. Verify symbol, spread, volume, SL/TP and the resulting
demo position before starting continuous monitoring:

```powershell
.\.venv\Scripts\python.exe .\demo_runner.py --loop
```

The loop polls every 10 seconds but evaluates only new completed M5 candles.
It uses a single-instance lock and idempotent per-candle event records. If it
halts due to uncertain order state, inspect MT5 orders/positions and the local
SQLite ledger before restarting.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Historical spreads, slippage and tick-volume VWAP are approximations. Backtests
and demo fills do not guarantee future performance. No live-account execution
is implemented.

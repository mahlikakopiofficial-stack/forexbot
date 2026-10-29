# Forex Research / MT5 Demo Lab

This repository is an educational EURUSD M15 research project. It contains
historical-data utilities, a paper backtester, and a separate MT5 **demo-only**
execution path. No profitability claim has been established.

## Safety boundaries

- No account number or password is stored in the repository. The code uses the
  account already open in the MT5 desktop terminal.
- The order executor refuses any account that is not reported by MT5 as DEMO.
- The expected server defaults to `XMGlobal-MT5 2`; an exact server mismatch
  stops the program. The executor also pins the first verified account login
  for the current process; `MT5_DEMO_LOGIN` can optionally require a specific
  demo login without sharing that login in chat.
- Demo order submission is **off by default**. It requires the exact opt-in
  token `MT5_DEMO_ORDER_ENABLED=YES_DEMO_ONLY`.
- Every new market position must have broker-side stop-loss and take-profit.
- The runner limits itself to EURUSD, one open EURUSD position, checks broker
  volume steps, spread, stop distance and account/terminal permissions, and
  persists candle/event state to prevent signal replay.
- If an order response or post-send position check is uncertain, the runner
  halts and requires manual reconciliation in MT5 instead of retrying.
- Never enable or use this project to send real-account orders.

The built-in EMA crossover is a **plumbing/test strategy**, not a validated
strategy, recommendation, or indication that the system will make money.
Default EMA and stop/target values are illustrative and must not be taken as
evidence of performance.

## Install and test

Use the same Windows machine where MT5 is installed:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

The local SQLite databases, downloaded market history, and runner lock file
are intentionally excluded by `.gitignore`. Keep your existing
`data\\forex_lab.db` and do not delete it when updating the source.

The historical backtester assumes EURUSD bars are Bid-based. The executor
checks the connected MT5 symbol chart mode and refuses a Last-based or
unverifiable chart. Historical per-bar spread is an approximation, not a
tick-by-tick reconstruction, so simulated costs are not exact fills.

## Read-only MT5 preflight

Open MT5, log in to the broker's **demo** account, select EURUSD in Market Watch,
and ensure algorithmic trading/external Python trading is allowed. Then run:

```powershell
python .\mt5_demo_executor.py preflight
```

This checks the connected terminal/account and quote. It does not submit an
order. The configured timezone defaults to `Europe/Athens` because the earlier
local diagnostics observed broker-clock timestamps matching that timezone.
If the broker/server or its timestamp behavior changes, verify it before
running the demo loop.

## Dry-run runner

First run a single check:

```powershell
python .\demo_runner.py --once
```

The first invocation stores the latest completed M15 candle as a checkpoint;
it intentionally does not replay an old signal. To keep checking for new
completed candles without sending orders:

```powershell
python .\demo_runner.py --loop
```

With the order gate disabled, crossover signals are recorded as dry-run events
in `data\demo_runner.sqlite3`. Stop the loop with Ctrl+C.

## Explicit MT5 demo execution

Do **not** use this until the read-only preflight, unit tests, and dry-run have
passed, and you have confirmed the MT5 terminal is on the intended demo
account. In the same PowerShell session only, set the exact expected server
and explicit demo-only token:

```powershell
$env:MT5_DEMO_SERVER = "XMGlobal-MT5 2"
# Optional: set your own demo login locally to lock to that account.
# $env:MT5_DEMO_LOGIN = "YOUR_DEMO_LOGIN"
$env:MT5_DEMO_ORDER_ENABLED = "YES_DEMO_ONLY"
python .\demo_runner.py --once
```

For continuous demo operation, use `--loop` instead of `--once`. The runner
only evaluates a newly completed M15 candle, and uses an illustrative EMA(12,
26) crossover with 0.01-lot volume, 20-pip stop and 40-pip target defaults.
These defaults are for integration testing and are not performance-validated.
The runner also defaults to at most three entries per UTC day and a daily
equity-loss block in the account's currency. The daily equity baseline is
recorded when the runner first observes each UTC date; this is not a
broker-enforced stop-loss. A single-instance operating-system lock prevents
two local runners from managing the same symbol simultaneously. An uncertain
order state causes a hard stop; inspect the MT5 terminal/History and the local
execution ledger before restarting.

The broker can reject orders due to execution mode, margin, market status,
volume limits, SL/TP rules or other server-side conditions. A passing unit test
cannot verify the actual terminal, broker permissions, market execution or
fills. These require an explicit manual check in the demo terminal.

## Commands

- `python .\check_mt5.py` — prior read-only connection/quote check (requires
  `MT5_PATH` to be configured as it was on your machine).
- `python .\sync_history.py` — synchronizes closed MT5 candles into the
  historical database.
- `python .\backtest.py audit` — validates the local stored historical data.
- `python .\\run_ema_backtest.py --fast 12 --slow 26` — runs a historical paper simulation of the same EMA signal used by the demo runner and writes summary, trades and equity-curve files under `reports\\ema_12_26`.
  By default this models 20-pip SL and 40-pip TP barriers from M15 OHLC;
  when both barriers are touched within one candle, it assumes the stop happened
  first. Short-side Ask prices are approximated as Bid plus that candle's
  spread. Intrabar exits are timestamped at the triggering candle's end because
  exact tick time is unavailable. These are conservative bar-based
  approximations, not tick-level fills.
  The backtest defaults to 50 base-currency units and an unleveraged exposure
  limit, so its position size is **not the same** as the demo runner's 0.01 lot.
  Set `--units`, `--starting-balance`, `--point-size`, `--slippage-points`,
  `--stop-loss-pips`, or `--take-profit-pips` to inspect different assumptions.
- `python .\smoke_backtest.py` — no-trade backtest pipeline smoke test.
- `python -m pytest -q` — full automated unit tests.

No real-account/live trading mode is included in the demo runner.

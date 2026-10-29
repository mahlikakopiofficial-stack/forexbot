# Forex Research / MT5 Demo Lab

This repository is an educational M15 research project for a selected broker symbol (initially EURUSD). It contains
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
- The runner allowlists EURUSD and the broker-listed EURUSD# variant, uses the
  single symbol selected through FOREX_SYMBOL, limits itself to one position
  on that symbol, and checks volume, spread, stop distance and account permissions.
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

## Read-only MT5 symbol diagnostic and preflight

Open MT5 and confirm it is connected to the intended **demo** account. Run:

```powershell
python .\\diagnose_mt5_symbol.py
```

The diagnostic reports exact symbol names, their trading modes, and whether a
valid quote is available. It may select the broker-listed EURUSD candidates
into Market Watch, but it never submits orders. In the supplied output EURUSD
was DISABLED while EURUSD# was FULL but not selected. The diagnostic now tries
to select that candidate and waits briefly for a valid Bid/Ask tick.

Only if the diagnostic confirms EURUSD# is FULL and returns a fresh, valid
quote, use the same symbol consistently for history, backtesting, and dry-run
signal evaluation. In the same PowerShell session:

```powershell
$env:FOREX_SYMBOL = "EURUSD#"
python .\\sync_history.py
python .\\verify_store.py
python .\\backtest.py audit
python .\\run_ema_backtest.py --fast 12 --slow 26
python .\\mt5_demo_executor.py preflight
python .\\demo_runner.py --once
```

This stores EURUSD# candles separately from the existing EURUSD rows in
`data\\forex_lab.db`. Do not compare old EURUSD history with dry-run signals
generated from EURUSD#. Confirm the quotes and converted timestamps are fresh
before interpreting results. The executor never switches accounts; the order
gate remains disabled unless the explicit token documented below is set.
Preflight and diagnostics do not submit orders.

## Expand the history before judging strategy quality

The first walk-forward report used only 5,000 M15 candles, roughly a few months
of broker history. That sample is too short to establish robust strategy
performance. The history sync now requests 20,000 completed candles by default;
it can be adjusted locally with `FOREX_HISTORY_BARS` (allowed range 100 to
100000). MT5 may return fewer bars if its chart-history limit is lower.

Keep MT5 open and connected to the intended demo account, then run:

```powershell
$env:FOREX_SYMBOL = "EURUSD#"
$env:FOREX_HISTORY_BARS = "20000"
python .\\sync_history.py
python .\\verify_store.py
python .\\backtest.py audit
python .\\walk_forward_ema.py --fast 12 --slow 26 --folds 5
```

Sync is additive: existing candles are checked for conflicts and are not silently
overwritten. Check the returned count and first/last candle timestamps. If fewer
than 20,000 bars are returned, raise MT5's "Max bars in chart" setting and sync
again. Review the audit's gaps before interpreting results; weekend/market
closures are expected, but unexpected gaps should be investigated. This remains
paper research only; more historical data cannot guarantee a profitable edge.

## Fixed-parameter walk-forward check

After the chronological split report, run the fixed EMA settings through five
sequential test windows. Each window uses only prior candles to warm up the
EMA; the warm-up section cannot open positions. Each fold is an independent
virtual-balance simulation, and the report shows returns by window rather than
pretending these are one compounded account.

```powershell
$env:FOREX_SYMBOL = "EURUSD#"
python .\\walk_forward_ema.py --fast 12 --slow 26 --folds 5
```

Reports are saved to `reports/ema_walk_forward_12_26`. Keep EMA parameters fixed
during this diagnostic; do not choose settings simply because one fold looks
good. A small number of profitable folds or a high pooled profit factor would
still not establish a durable edge. The dataset is short and its spread model
is approximate, so this remains exploratory paper research.

## Chronological strategy evaluation

After verifying the dry-run connection, evaluate the fixed example EMA settings
on a chronological train/holdout split. This uses the selected broker symbol's
stored history and the paper backtest cost assumptions; it does not connect to
MT5 or send broker orders.

```powershell
$env:FOREX_SYMBOL = "EURUSD#"
python .\\evaluate_ema_split.py --fast 12 --slow 26 --train-fraction 0.70
```

The report is saved to `reports/ema_split_12_26`, with separate train and
holdout metrics, trade CSVs, and equity curves. A small pre-split window is
used only to warm up the EMA; it cannot open positions. Both sections start
from the same virtual balance. Do not repeatedly tune EMA settings against the
holdout results: one split is an exploratory check, not proof of a durable edge.
Continue with paper evaluation only; this example strategy has not been proven
profitable.

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

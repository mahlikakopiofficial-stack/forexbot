# Three-Asset Historical Data Setup

This collector is separate from the existing M15 runner and uses the existing
SQLite database without deleting or replacing it.

## 1. Discover broker symbol names

With the MT5 desktop terminal open and connected, run:

\`\`\`powershell
python .\diagnose_research_symbols.py
\`\`\`

Record the exact Gold, EURUSD and GBPUSD symbol names. The script may select
matching symbols into Market Watch to request quotes. It does not place orders
or print account identifiers.

## 2. Configure exact symbols locally

Use the exact names returned by the diagnostic. Example only:

\`\`\`powershell
$env:RESEARCH_GOLD_SYMBOL = "GOLD#"
$env:RESEARCH_EURUSD_SYMBOL = "EURUSD#"
$env:RESEARCH_GBPUSD_SYMBOL = "GBPUSD#"
$env:RESEARCH_HISTORY_BARS = "20000"
\`\`\`

Do not copy the example Gold or GBPUSD names unless the diagnostic confirms
them for the connected broker.

## 3. Sync completed M5 and H1 candles

\`\`\`powershell
python .\sync_research_history.py
\`\`\`

The script reads completed candles only, stores M5 and H1 rows separately,
stores MT5 Unix timestamps as UTC, validates OHLC and timestamp order, checks
existing OHLC conflicts, and uses additive inserts. It refuses to create a
missing database or missing market_candles table.

If an old row has a different timestamp convention, the script stops on a
conflict rather than silently shifting or overwriting history. Resolve that
timestamp audit before syncing further.

## Notes

MT5 history availability depends on terminal chart-history settings and broker
retention. 20,000 bars is a request, not a guarantee. No strategy signals,
trading instructions or orders are produced.

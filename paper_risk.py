import math
import sqlite3
from pathlib import Path

from paper_positions import get_live_quote

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"

DEFAULT_SLIPPAGE_PER_FILL = 0.00001
DEFAULT_EXIT_COMMISSION_PER_SIDE = 0.0


def calculate_report(
    account,
    positions,
    bid,
    ask,
    slippage_per_fill=DEFAULT_SLIPPAGE_PER_FILL,
    exit_commission_per_side=DEFAULT_EXIT_COMMISSION_PER_SIDE,
):
    """Calculate hypothetical liquidation equity without writing data."""

    values = [bid, ask, slippage_per_fill, exit_commission_per_side]

    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("All prices and costs must be finite")

    if bid <= 0 or ask < bid:
        raise ValueError("Invalid bid/ask quote")

    if slippage_per_fill < 0 or exit_commission_per_side < 0:
        raise ValueError("Costs cannot be negative")

    cash = float(account["cash_balance"])
    realized = float(account["realized_pnl"])

    used_exposure = 0.0
    gross_unrealized = 0.0
    net_unrealized = 0.0
    estimated_spread_cost = 0.0
    estimated_slippage_cost = 0.0
    estimated_commission = 0.0
    details = []

    for position in positions:
        direction = position["direction"]
        units = float(position["quantity_units"])
        entry = float(position["entry_price"])

        if direction not in ("BUY", "SELL"):
            raise ValueError("Invalid direction in stored position")

        if (
            not math.isfinite(units)
            or not math.isfinite(entry)
            or units <= 0
            or entry <= 0
        ):
            raise ValueError("Invalid stored position size or price")

        # Use an estimated liquidation fill, including adverse slippage.
        if direction == "BUY":
            exit_fill = bid - slippage_per_fill
            gross_pnl = (exit_fill - entry) * units
        else:
            exit_fill = ask + slippage_per_fill
            gross_pnl = (entry - exit_fill) * units

        if exit_fill <= 0:
            raise ValueError("Invalid estimated liquidation price")

        entry_commission = float(position["commission_usd"])
        close_commission = exit_commission_per_side

        # Entry fill already includes entry spread and slippage.
        # Exit fill includes current spread and estimated exit slippage.
        net_pnl = gross_pnl - entry_commission - close_commission

        exposure = units * entry

        spread_cost = (
            float(position["spread_cost_usd"])
            + ((ask - bid) / 2) * units
        )

        slippage_cost = (
            float(position["slippage_cost_usd"])
            + slippage_per_fill * units
        )

        used_exposure += exposure
        gross_unrealized += gross_pnl
        net_unrealized += net_pnl
        estimated_spread_cost += spread_cost
        estimated_slippage_cost += slippage_cost
        estimated_commission += entry_commission + close_commission

        details.append({
            "id": position["id"],
            "direction": direction,
            "units": units,
            "entry_price": entry,
            "estimated_exit_price": exit_fill,
            "gross_unrealized_pnl": gross_pnl,
            "estimated_net_unrealized_pnl": net_pnl,
            "exposure": exposure,
        })

    equity = cash + net_unrealized
    available_exposure = cash - used_exposure

    return {
        "cash_balance": cash,
        "realized_pnl": realized,
        "used_exposure": used_exposure,
        "available_exposure": available_exposure,
        "gross_unrealized_pnl": gross_unrealized,
        "net_unrealized_pnl": net_unrealized,
        "estimated_spread_cost": estimated_spread_cost,
        "estimated_slippage_cost": estimated_slippage_cost,
        "estimated_commission": estimated_commission,
        "estimated_equity": equity,
        "positions": details,
    }


def main():
    if not DB_FILE.is_file():
        raise SystemExit(f"Database not found: {DB_FILE}")

    # Obtain a validated, read-only quote.
    quote = get_live_quote()

    # Query-only mode prevents accidental database modification.
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")

        row = conn.execute("""
            SELECT currency, initial_balance, cash_balance, realized_pnl
            FROM paper_account
            WHERE account_id = 1
        """).fetchone()

        if row is None:
            raise SystemExit("Virtual account not found")

        positions = conn.execute("""
            SELECT id, direction, quantity_units, entry_price,
                   commission_usd, spread_cost_usd, slippage_cost_usd
            FROM paper_trades
            WHERE status = 'OPEN'
            ORDER BY id
        """).fetchall()

    report = calculate_report(
        dict(row),
        [dict(position) for position in positions],
        quote["bid"],
        quote["ask"],
    )

    print("\nPAPER ACCOUNT RISK REPORT — READ ONLY")
    print("Symbol: EURUSD")
    print("Quote timestamp:", quote["tick_time_utc"])
    print(f"Bid: {quote['bid']:.5f}")
    print(f"Ask: {quote['ask']:.5f}")
    print(f"Open positions: {len(report['positions'])}")
    print(f"Virtual cash: ${report['cash_balance']:.2f}")
    print(f"Used notional exposure: ${report['used_exposure']:.2f}")
    print(f"Remaining cash exposure capacity: "
          f"${report['available_exposure']:.2f}")
    print(f"Gross unrealized P&L: "
          f"${report['gross_unrealized_pnl']:.4f}")
    print(f"Estimated net unrealized P&L: "
          f"${report['net_unrealized_pnl']:.4f}")
    print(f"Estimated equity: ${report['estimated_equity']:.4f}")
    print(f"Realized P&L: ${report['realized_pnl']:.4f}")
    print(f"Estimated spread cost: "
          f"${report['estimated_spread_cost']:.4f}")
    print(f"Estimated slippage cost: "
          f"${report['estimated_slippage_cost']:.4f}")
    print(f"Estimated commissions: "
          f"${report['estimated_commission']:.4f}")

    for item in report["positions"]:
        print(
            f"\nPosition #{item['id']} {item['direction']} "
            f"{item['units']} units"
        )
        print(f"Entry price: {item['entry_price']:.5f}")
        print(f"Estimated exit: {item['estimated_exit_price']:.5f}")
        print(
            "Estimated net unrealized P&L: "
            f"${item['estimated_net_unrealized_pnl']:.4f}"
        )

    print("\nThis report does not modify the database.")
    print("No broker orders were submitted.")


if __name__ == "__main__":
    main()
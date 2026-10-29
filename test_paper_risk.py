import pytest

from paper_risk import calculate_report


def test_empty_account_equity_equals_cash():
    report = calculate_report(
        {"cash_balance": 100.0, "realized_pnl": 0.0},
        [],
        bid=1.10000,
        ask=1.10020,
    )

    assert report["estimated_equity"] == pytest.approx(100.0)
    assert report["used_exposure"] == pytest.approx(0.0)
    assert report["net_unrealized_pnl"] == pytest.approx(0.0)


def test_open_buy_includes_estimated_exit_costs():
    account = {"cash_balance": 100.0, "realized_pnl": 0.0}

    positions = [{
        "id": 1,
        "direction": "BUY",
        "quantity_units": 50.0,
        "entry_price": 1.10020,
        "commission_usd": 0.01,
        "spread_cost_usd": 0.005,
        "slippage_cost_usd": 0.0,
    }]

    report = calculate_report(
        account,
        positions,
        bid=1.10100,
        ask=1.10120,
        slippage_per_fill=0.00001,
        exit_commission_per_side=0.01,
    )

    assert report["gross_unrealized_pnl"] == pytest.approx(0.0395)
    assert report["net_unrealized_pnl"] == pytest.approx(0.0195)
    assert report["estimated_equity"] == pytest.approx(100.0195)
    assert report["used_exposure"] == pytest.approx(55.01)


def test_open_sell_uses_ask_to_estimate_exit():
    positions = [{
        "id": 2,
        "direction": "SELL",
        "quantity_units": 50.0,
        "entry_price": 1.10100,
        "commission_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
    }]

    report = calculate_report(
        {"cash_balance": 100.0, "realized_pnl": 0.0},
        positions,
        bid=1.10000,
        ask=1.10020,
        slippage_per_fill=0.00001,
        exit_commission_per_side=0.0,
    )

    assert report["positions"][0]["estimated_exit_price"] == pytest.approx(
        1.10021
    )
    assert report["net_unrealized_pnl"] == pytest.approx(0.0395)


def test_invalid_quote_is_rejected():
    with pytest.raises(ValueError, match="Invalid bid/ask"):
        calculate_report(
            {"cash_balance": 100.0, "realized_pnl": 0.0},
            [],
            bid=1.10100,
            ask=1.10000,
        )
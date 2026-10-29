import sqlite3

import pytest

from paper_positions import (
    open_paper_position,
    close_paper_position,
)


def make_test_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE strategy_signals (
                id INTEGER PRIMARY KEY
            );

            CREATE TABLE paper_account (
                account_id INTEGER PRIMARY KEY,
                currency TEXT NOT NULL,
                initial_balance REAL NOT NULL,
                cash_balance REAL NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                created_at_utc TEXT NOT NULL
            );

            CREATE TABLE paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_time_utc TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_time_utc TEXT,
                exit_price REAL,
                quantity_units REAL NOT NULL,
                spread_cost_usd REAL NOT NULL DEFAULT 0,
                commission_usd REAL NOT NULL DEFAULT 0,
                slippage_cost_usd REAL NOT NULL DEFAULT 0,
                pnl_usd REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                FOREIGN KEY (signal_id)
                    REFERENCES strategy_signals(id)
            );

            INSERT INTO paper_account
            VALUES (1, 'USD', 100.0, 100.0, 0.0,
                    '2026-10-29T00:00:00Z');
        """)


def test_buy_position_persists_and_updates_balance(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    make_test_db(db)
    monkeypatch.setattr("paper_positions.DB_FILE", db)

    opened = open_paper_position(
        "BUY", 50, 1.10000, 1.10020,
        "2026-10-29T09:00:00Z",
        slippage_per_fill=0,
        commission_per_side=0.01,
    )

    assert opened["entry_price"] == pytest.approx(1.10020)

    closed = close_paper_position(
        opened["trade_id"], 1.10100, 1.10120,
        "2026-10-29T09:15:00Z",
        slippage_per_fill=0,
        commission_per_side=0.01,
    )

    assert closed["net_pnl_usd"] == pytest.approx(0.02)

    with sqlite3.connect(db) as conn:
        row = conn.execute("""
            SELECT status, pnl_usd
            FROM paper_trades WHERE id = ?
        """, (opened["trade_id"],)).fetchone()

        account = conn.execute("""
            SELECT cash_balance, realized_pnl
            FROM paper_account WHERE account_id = 1
        """).fetchone()

    assert row[0] == "CLOSED"
    assert row[1] == pytest.approx(0.02)
    assert account[0] == pytest.approx(100.02)
    assert account[1] == pytest.approx(0.02)


def test_sell_position_calculates_profit(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    make_test_db(db)
    monkeypatch.setattr("paper_positions.DB_FILE", db)

    opened = open_paper_position(
        "SELL", 50, 1.10100, 1.10120,
        "2026-10-29T09:00:00Z",
        slippage_per_fill=0,
        commission_per_side=0,
    )

    closed = close_paper_position(
        opened["trade_id"], 1.10000, 1.10020,
        "2026-10-29T09:15:00Z",
        slippage_per_fill=0,
        commission_per_side=0,
    )

    assert closed["net_pnl_usd"] == pytest.approx(0.04)


def test_blocks_exposure_over_virtual_cash(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    make_test_db(db)
    monkeypatch.setattr("paper_positions.DB_FILE", db)

    with pytest.raises(ValueError, match="1:1 exposure limit"):
        open_paper_position(
            "BUY", 100, 1.10000, 1.10020,
            "2026-10-29T09:00:00Z",
            slippage_per_fill=0,
        )


def test_prevents_closing_same_position_twice(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    make_test_db(db)
    monkeypatch.setattr("paper_positions.DB_FILE", db)

    opened = open_paper_position(
        "BUY", 50, 1.10000, 1.10020,
        "2026-10-29T09:00:00Z",
        slippage_per_fill=0,
    )

    close_paper_position(
        opened["trade_id"], 1.10100, 1.10120,
        "2026-10-29T09:15:00Z",
        slippage_per_fill=0,
    )

    with pytest.raises(ValueError, match="No open paper position"):
        close_paper_position(
            opened["trade_id"], 1.10100, 1.10120,
            "2026-10-29T09:30:00Z",
            slippage_per_fill=0,
        )
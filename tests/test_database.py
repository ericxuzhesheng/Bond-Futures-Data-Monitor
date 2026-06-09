from bond_futures_monitor.config import get_settings
from bond_futures_monitor.database import connect, init_db, insert_futures_quotes


def futures_fixture(date: str = "2026-06-08") -> list[dict[str, object]]:
    return [
        {
            "date": date,
            "contract": contract,
            "close_price": close,
            "daily_return": ret,
            "volume": volume,
            "open_interest": oi,
            "data_source": f"akshare_cffex_daily:{date.replace('-', '')}",
        }
        for contract, close, ret, volume, oi in [
            ("TS", 101.0, 0.001, 1000, 2000),
            ("TF", 102.0, 0.001, 1000, 2000),
            ("T", 103.0, 0.001, 1000, 2000),
            ("TL", 104.0, 0.001, 1000, 2000),
        ]
    ]


def test_database_initialization(tmp_path):
    db_path = tmp_path / "monitor.db"
    with connect(db_path) as conn:
        init_db(conn)
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    assert "futures_quotes" in tables
    assert "open_market_operations" in tables
    assert "daily_market_signals" in tables
    assert "run_log" in tables


def test_duplicate_insert_handling(tmp_path):
    db_path = tmp_path / "monitor.db"
    rows = futures_fixture()
    with connect(db_path) as conn:
        init_db(conn)
        first = insert_futures_quotes(conn, rows)
        second = insert_futures_quotes(conn, rows)
        count = conn.execute("SELECT COUNT(*) AS n FROM futures_quotes").fetchone()["n"]
    assert first == 4
    assert second == 0
    assert count == 4


def test_live_data_is_default(monkeypatch):
    monkeypatch.delenv("USE_LIVE_DATA", raising=False)
    assert get_settings().use_live_data is True

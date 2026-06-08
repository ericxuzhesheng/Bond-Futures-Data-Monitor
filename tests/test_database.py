from bond_futures_monitor.collectors.futures import sample_futures_quotes
from bond_futures_monitor.database import connect, init_db, insert_futures_quotes
from bond_futures_monitor.config import get_settings


def test_database_initialization(tmp_path):
    db_path = tmp_path / "monitor.db"
    with connect(db_path) as conn:
        init_db(conn)
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert "futures_quotes" in tables
    assert "daily_market_signals" in tables
    assert "run_log" in tables


def test_duplicate_insert_handling(tmp_path):
    db_path = tmp_path / "monitor.db"
    rows = sample_futures_quotes("2026-06-08")
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

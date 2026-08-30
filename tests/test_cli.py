"""Tests for CLI helpers and config."""

import pytest
import bond_futures_monitor.cli as cli_module
from bond_futures_monitor.cli import resolve_run_date, run_daily_pipeline
from bond_futures_monitor.config import get_settings
from bond_futures_monitor.database import connect, init_db, insert_futures_quotes


RUN_DATE = "2026-06-08"


def _futures_row(close_price: float) -> dict[str, object]:
    return {
        "date": RUN_DATE,
        "contract": "T",
        "close_price": close_price,
        "daily_return": 0.001,
        "volume": 1000,
        "open_interest": 2000,
        "data_source": "akshare_cffex_daily:test",
    }


def test_resolve_run_date_passthrough():
    assert resolve_run_date("2026-06-08") == "2026-06-08"


def test_resolve_run_date_today_returns_iso_string():
    result = resolve_run_date("today")
    parts = result.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 4


def test_resolve_run_date_invalid_raises():
    with pytest.raises(ValueError):
        resolve_run_date("not-a-date")


def test_config_live_data_off(monkeypatch):
    monkeypatch.setenv("USE_LIVE_DATA", "0")
    assert get_settings().use_live_data is False


def test_config_live_data_on_explicit(monkeypatch):
    monkeypatch.setenv("USE_LIVE_DATA", "true")
    assert get_settings().use_live_data is True


def test_config_database_path_default(monkeypatch):
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    path = get_settings().database_path
    assert str(path).endswith("bond_futures_monitor.db")


def test_run_daily_pipeline_rejects_disabled_live_data(tmp_path):
    with pytest.raises(RuntimeError, match="requires real data"):
        run_daily_pipeline(None, "2026-06-08", False, tmp_path)


def test_run_daily_pipeline_rolls_back_partial_refresh(monkeypatch, tmp_path):
    db_path = tmp_path / "monitor.db"
    with connect(db_path) as conn:
        init_db(conn)
        insert_futures_quotes(conn, [_futures_row(100.0)])
        conn.commit()

        monkeypatch.setattr(cli_module, "collect_futures_quotes", lambda *_: [_futures_row(101.0)])
        def fail_bond_yields(*_):
            raise RuntimeError("upstream unavailable")

        monkeypatch.setattr(cli_module, "collect_bond_yields", fail_bond_yields)

        with pytest.raises(RuntimeError, match="upstream unavailable"):
            run_daily_pipeline(conn, RUN_DATE, True, tmp_path)

        row = conn.execute(
            "SELECT close_price FROM futures_quotes WHERE date = ? AND contract = 'T'",
            (RUN_DATE,),
        ).fetchone()
        assert row["close_price"] == 100.0

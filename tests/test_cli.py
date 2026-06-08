"""Tests for CLI helpers and config."""

import pytest
from bond_futures_monitor.cli import resolve_run_date
from bond_futures_monitor.config import get_settings


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

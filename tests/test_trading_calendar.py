"""Holiday regression coverage for scheduled reports."""

from types import SimpleNamespace

import akshare as ak
import pandas as pd
import pytest
import tushare as ts

from bond_futures_monitor import trading_calendar as calendar_module


@pytest.fixture(autouse=True)
def isolated_calendar(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(calendar_module, "retry_call", lambda func, **kwargs: func())
    monkeypatch.setattr(ak, "tool_trade_date_hist_sina", lambda: pd.DataFrame({
        "trade_date": ["2026-09-24", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12"],
    }))


@pytest.mark.parametrize("run_date", ["2026-09-25", "2026-09-26", "2026-10-01", "2026-10-07", "2026-10-10"])
def test_exchange_holidays_and_makeup_workday_are_closed(run_date):
    assert calendar_module.is_trading_day(run_date) is False


@pytest.mark.parametrize("run_date", ["2026-09-24", "2026-09-28", "2026-09-30", "2026-10-08"])
def test_real_trading_days_remain_open(run_date):
    assert calendar_module.is_trading_day(run_date) is True


@pytest.mark.parametrize("days", [[], ["2025-01-02", "2025-12-31"], ["2026-09-24", None, "2026-10-08"]])
def test_incomplete_calendar_is_not_a_holiday(monkeypatch, days):
    monkeypatch.setattr(ak, "tool_trade_date_hist_sina", lambda: pd.DataFrame({"trade_date": days}))
    with pytest.raises(RuntimeError, match="Cannot verify trading calendar"):
        calendar_module.is_trading_day("2026-09-25")


def test_calendar_outage_fails_instead_of_skipping(monkeypatch):
    def fail():
        raise OSError("upstream unavailable")
    monkeypatch.setattr(ak, "tool_trade_date_hist_sina", fail)
    with pytest.raises(RuntimeError, match="Cannot verify trading calendar"):
        calendar_module.is_trading_day("2026-09-28")


@pytest.mark.parametrize("is_open", [0, 1])
def test_cffex_calendar_takes_precedence(monkeypatch, is_open):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    def fetch(**kwargs):
        assert kwargs == {"exchange": "CFFEX", "start_date": "20260925", "end_date": "20260925"}
        return pd.DataFrame([{"exchange": "CFFEX", "cal_date": "20260925", "is_open": is_open}])
    monkeypatch.setattr(ts, "pro_api", lambda token: SimpleNamespace(fut_trade_cal=fetch))
    assert calendar_module.is_trading_day("2026-09-25") is bool(is_open)


def test_unavailable_cffex_calendar_uses_public_calendar(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    monkeypatch.setattr(ts, "pro_api", lambda token: SimpleNamespace(fut_trade_cal=lambda **kwargs: pd.DataFrame()))
    assert calendar_module.is_trading_day("2026-09-25") is False

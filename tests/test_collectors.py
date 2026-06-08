"""Tests for all four collector modules (sample-fallback path)."""

import pytest
from bond_futures_monitor.collectors.futures import collect_futures_quotes, sample_futures_quotes
from bond_futures_monitor.collectors.funding import collect_funding_rates, sample_funding_rates
from bond_futures_monitor.collectors.yield_curve import collect_bond_yields, sample_bond_yields
from bond_futures_monitor.collectors.policy_news import collect_policy_news, sample_policy_news

RUN_DATE = "2026-06-08"
REQUIRED_RATE_NAMES = {"DR001", "DR007", "R007", "SHIBOR_ON", "SHIBOR_7D"}
REQUIRED_TENORS = {"1Y", "2Y", "5Y", "10Y", "30Y"}
REQUIRED_CONTRACTS = {"TS", "TF", "T", "TL"}


# ── futures ──────────────────────────────────────────────────────────────────

def test_sample_futures_quotes_structure():
    rows = sample_futures_quotes(RUN_DATE)
    assert len(rows) == 4
    contracts = {r["contract"] for r in rows}
    assert contracts == REQUIRED_CONTRACTS
    for row in rows:
        assert row["date"] == RUN_DATE
        assert isinstance(row["close_price"], float)
        assert isinstance(row["volume"], (int, float))
        assert row["data_source"] == "sample_fallback"


def test_collect_futures_quotes_uses_sample_when_live_disabled():
    rows = collect_futures_quotes(RUN_DATE, use_live_data=False)
    assert {r["contract"] for r in rows} == REQUIRED_CONTRACTS
    assert all(r["data_source"] == "sample_fallback" for r in rows)


# ── funding ───────────────────────────────────────────────────────────────────

def test_sample_funding_rates_structure():
    rows = sample_funding_rates(RUN_DATE)
    names = {r["rate_name"] for r in rows}
    assert names == REQUIRED_RATE_NAMES
    for row in rows:
        assert row["date"] == RUN_DATE
        assert isinstance(row["rate_value"], float)
        assert row["data_source"] == "sample_fallback"


def test_collect_funding_rates_uses_sample_when_live_disabled():
    rows = collect_funding_rates(RUN_DATE, use_live_data=False)
    assert {r["rate_name"] for r in rows} == REQUIRED_RATE_NAMES
    assert all(r["data_source"] == "sample_fallback" for r in rows)


def test_collect_funding_rates_falls_back_when_no_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    rows = collect_funding_rates(RUN_DATE, use_live_data=True)
    assert rows, "should fall back to sample data"
    assert all(r["data_source"] == "sample_fallback" for r in rows)


# ── yield curve ───────────────────────────────────────────────────────────────

def test_sample_bond_yields_structure():
    rows = sample_bond_yields(RUN_DATE)
    tenors = {r["tenor"] for r in rows}
    assert tenors == REQUIRED_TENORS
    for row in rows:
        assert row["date"] == RUN_DATE
        assert isinstance(row["yield_value"], float)
        assert row["data_source"] == "sample_fallback"


def test_collect_bond_yields_uses_sample_when_live_disabled():
    rows = collect_bond_yields(RUN_DATE, use_live_data=False)
    assert {r["tenor"] for r in rows} == REQUIRED_TENORS
    assert all(r["data_source"] == "sample_fallback" for r in rows)


def test_collect_bond_yields_falls_back_when_no_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    rows = collect_bond_yields(RUN_DATE, use_live_data=True)
    assert rows, "should fall back to sample data"
    assert all(r["data_source"] == "sample_fallback" for r in rows)


# ── policy news ───────────────────────────────────────────────────────────────

def test_sample_policy_news_structure():
    rows = sample_policy_news(RUN_DATE)
    assert len(rows) >= 1
    for row in rows:
        assert row["date"] == RUN_DATE
        assert row["title"]
        assert row["content"]
        assert row["data_source"] == "sample_fallback"


def test_collect_policy_news_uses_sample_when_live_disabled():
    rows = collect_policy_news(RUN_DATE, use_live_data=False)
    assert rows
    assert all(r["data_source"] == "sample_fallback" for r in rows)


def test_collect_policy_news_falls_back_when_no_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    rows = collect_policy_news(RUN_DATE, use_live_data=True)
    assert rows, "should fall back to sample data"
    assert all(r["data_source"] == "sample_fallback" for r in rows)

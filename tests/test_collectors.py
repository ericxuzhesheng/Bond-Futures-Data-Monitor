"""Tests for collector failure behavior and row normalization."""

import math

import pytest

import bond_futures_monitor.collectors.futures as futures_module
from bond_futures_monitor.collectors.funding import _validated_rate, collect_funding_rates
from bond_futures_monitor.collectors.futures import _require_float, collect_futures_quotes
from bond_futures_monitor.collectors.open_market import collect_open_market_operations, parse_omo_text
from bond_futures_monitor.collectors.policy_news import collect_policy_news
from bond_futures_monitor.collectors.policy_news import _is_fixed_income_relevant
from bond_futures_monitor.collectors.yield_curve import _rows_from_curve, _validated_yield, collect_bond_yields


RUN_DATE = "2026-06-08"


def test_collectors_reject_disabled_live_data():
    collectors = [
        collect_futures_quotes,
        collect_bond_yields,
        collect_funding_rates,
        collect_open_market_operations,
        collect_policy_news,
    ]
    for collector in collectors:
        with pytest.raises(RuntimeError, match="Sample data is disabled"):
            collector(RUN_DATE, use_live_data=False)


def test_tushare_collectors_require_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    # collect_bond_yields falls back to AkShare when Tushare token is absent,
    # so it no longer raises on missing token.
    for collector in [collect_funding_rates, collect_policy_news]:
        with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
            collector(RUN_DATE, use_live_data=True)


def test_open_market_collector_requires_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
        collect_open_market_operations(RUN_DATE, use_live_data=True)


def test_parse_omo_text_extracts_operation_maturity_net_and_rate():
    rows = parse_omo_text(
        "2026-06-05",
        "央行开展公开市场逆回购操作",
        "中国人民银行开展100亿元7天期逆回购操作，操作利率1.40%。今日有30亿元7天期逆回购到期，净投放70亿元。",
        "tushare_news_cls:2026-06-05",
    )
    assert rows
    row = rows[0]
    assert row["operation_type"] == "reverse_repo"
    assert row["tenor_days"] == 7
    assert row["operation_amount"] == 100.0
    assert row["maturity_amount"] == 30.0
    assert row["net_injection_amount"] == 70.0
    assert row["operation_rate"] == 1.4


def test_parse_omo_text_handles_maturity_only_as_net_withdrawal():
    rows = parse_omo_text(
        "2026-06-08",
        "投资日历：资本市场大事提醒",
        "今日有110亿元7天期逆回购到期。",
        "tushare_news_cls:2026-06-08",
    )
    assert rows[0]["operation_amount"] == 0.0
    assert rows[0]["maturity_amount"] == 110.0
    assert rows[0]["net_injection_amount"] == -110.0


def test_require_float_rejects_missing_and_nan_values():
    assert _require_float("102.5", "close", "T") == 102.5
    assert _require_float(0, "volume", "T") == 0.0
    with pytest.raises(RuntimeError, match="Missing required field 'close'"):
        _require_float(None, "close", "T")
    with pytest.raises(RuntimeError, match="Missing required field 'close'"):
        _require_float("", "close", "T")
    with pytest.raises(RuntimeError, match="NaN"):
        _require_float(math.nan, "close", "T")


def test_collect_futures_quotes_merges_cffex_with_sina_fallback(monkeypatch):
    def fake_cffex(run_date):
        return [
            {"date": run_date, "contract": c, "close_price": 100.0, "daily_return": 0.001,
             "volume": 1.0, "open_interest": 1.0, "data_source": "akshare_cffex_daily:test"}
            for c in ("TS", "TF", "T")
        ]

    def fake_sina(run_date, contracts):
        assert contracts == ("TL",)
        return [
            {"date": run_date, "contract": "TL", "close_price": 110.0, "daily_return": 0.002,
             "volume": 1.0, "open_interest": 1.0, "data_source": "akshare_sina_main_daily:TL0"}
        ]

    monkeypatch.setattr(futures_module, "_collect_cffex_daily", fake_cffex)
    monkeypatch.setattr(futures_module, "_collect_sina_main", fake_sina)

    rows = collect_futures_quotes(RUN_DATE)
    by_contract = {row["contract"]: row for row in rows}
    assert set(by_contract) == {"TS", "TF", "T", "TL"}
    assert by_contract["T"]["data_source"].startswith("akshare_cffex_daily")
    assert by_contract["TL"]["data_source"].startswith("akshare_sina_main_daily")


def test_collect_futures_quotes_raises_when_coverage_incomplete(monkeypatch):
    monkeypatch.setattr(futures_module, "_collect_cffex_daily", lambda run_date: [])
    monkeypatch.setattr(futures_module, "_collect_sina_main", lambda run_date, contracts: [])
    with pytest.raises(RuntimeError, match="coverage is incomplete"):
        collect_futures_quotes(RUN_DATE)


def test_sina_daily_return_uses_previous_settle():
    pd = pytest.importorskip("pandas")
    history = pd.DataFrame(
        [
            {"date": "2026-06-05", "open": 99.0, "close": 99.5, "settle": 99.6, "volume": 10.0, "hold": 100.0},
            {"date": "2026-06-08", "open": 99.8, "close": 100.1, "settle": 100.0, "volume": 12.0, "hold": 105.0},
        ]
    )
    row = futures_module._sina_row(RUN_DATE, "T", "T0", history, 1)
    assert row["close_price"] == 100.1
    assert row["daily_return"] == pytest.approx(100.1 / 99.6 - 1)


def test_validated_rate_rejects_implausible_values():
    assert _validated_rate("DR007", "1.55") == 1.55
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_rate("DR007", 0.0)
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_rate("DR007", 55.0)
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_rate("DR007", math.nan)
    with pytest.raises(RuntimeError, match="not numeric"):
        _validated_rate("DR007", None)


def test_validated_yield_rejects_implausible_values():
    assert _validated_yield("10Y", "2.15") == 2.15
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_yield("10Y", -1.0)
    with pytest.raises(RuntimeError, match="not numeric"):
        _validated_yield("10Y", "n/a")


def test_rows_from_curve_matches_terms_with_tolerance():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame(
        [
            {"curve_term": "1.0001", "yield": 1.4},
            {"curve_term": "2.0", "yield": 1.5},
            {"curve_term": "5.0", "yield": 1.7},
            {"curve_term": "9.9999", "yield": 2.0},
            {"curve_term": "30.0", "yield": 2.3},
        ]
    )
    rows = _rows_from_curve(df, RUN_DATE, "20260608")
    assert {row["tenor"] for row in rows} == {"1Y", "2Y", "5Y", "10Y", "30Y"}
    by_tenor = {row["tenor"]: row["yield_value"] for row in rows}
    assert by_tenor["10Y"] == 2.0


def test_policy_news_relevance_filter_keeps_rates_and_drops_equity_noise():
    assert _is_fixed_income_relevant("央行公开市场净投放呵护流动性，DR007回落。")
    assert _is_fixed_income_relevant("财政部公布地方债发行安排，国债收益率波动。")
    assert _is_fixed_income_relevant("国家发改委将安排超长期特别国债资金支持城市地下管网建设。")
    assert not _is_fixed_income_relevant("美股加密货币概念股普涨，亚马逊发行公司债。")
    assert not _is_fixed_income_relevant("某公司拟减持股份并推出员工持股计划。")
    assert not _is_fixed_income_relevant("电池ETF连续两日获资金加仓。")
    assert not _is_fixed_income_relevant("上市公司回购股份价格上限调整。")
    assert not _is_fixed_income_relevant("公司拟向银行间交易商协会注册发行债务融资工具。")
    assert not _is_fixed_income_relevant("科技ETF称降息交易有望提振成长股。")

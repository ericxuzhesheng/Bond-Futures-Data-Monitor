"""Tests for collector failure behavior and row normalization."""

import pytest

from bond_futures_monitor.collectors.funding import collect_funding_rates
from bond_futures_monitor.collectors.futures import collect_futures_quotes
from bond_futures_monitor.collectors.policy_news import collect_policy_news
from bond_futures_monitor.collectors.policy_news import _is_fixed_income_relevant
from bond_futures_monitor.collectors.yield_curve import collect_bond_yields


RUN_DATE = "2026-06-08"


def test_collectors_reject_disabled_live_data():
    collectors = [
        collect_futures_quotes,
        collect_bond_yields,
        collect_funding_rates,
        collect_policy_news,
    ]
    for collector in collectors:
        with pytest.raises(RuntimeError, match="Sample data is disabled"):
            collector(RUN_DATE, use_live_data=False)


def test_tushare_collectors_require_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    for collector in [collect_bond_yields, collect_funding_rates, collect_policy_news]:
        with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
            collector(RUN_DATE, use_live_data=True)


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

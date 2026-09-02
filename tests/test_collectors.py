"""Tests for collector failure behavior and row normalization."""

import math

import pytest

import bond_futures_monitor.collectors.funding as funding_module
import bond_futures_monitor.collectors.futures as futures_module
import bond_futures_monitor.collectors.open_market as open_market_module
import bond_futures_monitor.collectors.policy_news as policy_news_module
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


def test_funding_collector_uses_open_source_without_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    rows = [
        {"date": RUN_DATE, "rate_name": name, "rate_value": 1.5, "data_source": "akshare:test"}
        for name in ("FDR001", "FDR007", "FR007", "SHIBOR_ON", "SHIBOR_7D")
    ]
    monkeypatch.setattr(funding_module, "_collect_akshare", lambda run_date: rows)
    collected = collect_funding_rates(RUN_DATE)
    assert {row["rate_name"] for row in collected} == {
        "FDR001", "FDR007", "FR007", "SHIBOR_ON", "SHIBOR_7D"
    }


def test_funding_uses_current_repo_csv_when_history_endpoint_breaks(monkeypatch):
    pd = pytest.importorskip("pandas")
    ak = pytest.importorskip("akshare")
    monkeypatch.setattr(funding_module, "retry_call", lambda func, description: func())
    monkeypatch.setattr(ak, "repo_rate_hist", lambda **kwargs: (_ for _ in ()).throw(KeyError("frValueMap")))
    monkeypatch.setattr(
        ak,
        "repo_rate_query",
        lambda symbol: pd.DataFrame([{
            "date": pd.Timestamp(RUN_DATE).date(),
            **({"FR001": 1.4, "FR007": 1.5, "FR014": 1.6}
               if symbol == "回购定盘利率"
               else {"FDR001": 1.3, "FDR007": 1.4, "FDR014": 1.5}),
        }]),
    )
    monkeypatch.setattr(
        ak,
        "macro_china_shibor_all",
        lambda: pd.DataFrame([{"日期": RUN_DATE, "O/N-定价": 1.31, "1W-定价": 1.41}]),
    )
    rows = funding_module._collect_akshare(RUN_DATE)
    assert {row["rate_name"] for row in rows} == {
        "FDR001", "FDR007", "FR007", "SHIBOR_ON", "SHIBOR_7D"
    }


def test_text_collectors_tolerate_no_accessible_news(monkeypatch):
    monkeypatch.setattr(open_market_module, "_collect_pbc_official", lambda run_date: [])
    monkeypatch.setattr(open_market_module, "_collect_tushare_news", lambda run_date: [])
    monkeypatch.setattr(policy_news_module, "_collect_tushare_news", lambda run_date: [])
    assert collect_open_market_operations(RUN_DATE, use_live_data=True) == []
    assert collect_policy_news(RUN_DATE, use_live_data=True) == []


def test_pbc_notice_links_selects_the_requested_date():
    html = """
    <table>
      <tr><td><a href="/notice/today/index.html">公开市场业务交易公告 [2026]第100号</a>
      <span>2026-06-08</span></td></tr>
      <tr><td><a href="/notice/old/index.html">公开市场业务交易公告 [2026]第99号</a>
      <span>2026-06-05</span></td></tr>
    </table>
    """
    links = open_market_module._pbc_notice_links(html, RUN_DATE)
    assert links == [
        (
            "公开市场业务交易公告 [2026]第100号",
            "https://www.pbc.gov.cn/notice/today/index.html",
        )
    ]


def test_official_omo_terms_merge_with_news_maturity():
    official = [{
        "date": RUN_DATE, "operation_type": "reverse_repo", "tenor_days": 7,
        "operation_amount": 100.0, "maturity_amount": 0.0, "net_injection_amount": 100.0,
        "operation_rate": 1.4, "source_title": "人民银行公告",
        "data_source": "pbc_official:https://example.test", "_net_complete": False,
    }]
    news = [{
        "date": RUN_DATE, "operation_type": "reverse_repo", "tenor_days": 7,
        "operation_amount": 90.0, "maturity_amount": 30.0, "net_injection_amount": 60.0,
        "operation_rate": None, "source_title": "媒体摘要", "data_source": "akshare_cls:test",
    }]
    rows = open_market_module._merge_official_and_news_rows(official, news)
    assert rows[0]["operation_amount"] == 100.0
    assert rows[0]["maturity_amount"] == 30.0
    assert rows[0]["net_injection_amount"] == 70.0
    assert rows[0]["operation_rate"] == 1.4
    assert rows[0]["data_source"].startswith("pbc_official:")


def test_zero_operation_notice_is_not_dropped():
    rows = open_market_module._parse_zero_operation_notice(
        RUN_DATE,
        "公开市场业务交易公告 [2026]第100号",
        "2026年6月8日7天期逆回购操作量为零。",
        "pbc_official:https://example.test",
    )
    assert rows[0]["tenor_days"] == 7
    assert rows[0]["operation_amount"] == 0.0


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


@pytest.mark.parametrize("text", [
    "下周央行公开市场将有22655亿元逆回购到期。",
    "本周央行开展620亿元逆回购操作，本周净回笼6165亿元。",
    "央行将在7月29日至7月31日开展隔夜逆回购操作，每日6000亿元。",
    "央行公告，7月15日将以固定数量、利率招标方式开展14000亿元买断式逆回购操作。",
])
def test_omo_does_not_treat_aggregate_or_planned_operations_as_today(text):
    assert parse_omo_text("2026-07-15", "央行公开市场消息", text, "cls") == []


def test_omo_rate_does_not_capture_unrelated_probability():
    rows = parse_omo_text("2026-07-27", "央行逆回购操作",
        "央行开展100亿元7天期逆回购操作。美联储维持利率不变的概率为65.3%。", "cls")
    assert rows[0]["operation_rate"] is None


def test_omo_keeps_current_maturity_when_digest_also_has_future_plans():
    rows = parse_omo_text("2026-07-29", "投资日历",
        "今日有760亿元7天期逆回购到期。央行将在下周开展6000亿元隔夜逆回购操作。", "cls")
    assert rows[0]["tenor_days"] == 7
    assert rows[0]["maturity_amount"] == 760


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

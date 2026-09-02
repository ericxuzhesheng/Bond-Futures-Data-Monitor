import pytest

from bond_futures_monitor.collectors.macro_history import (
    _indicator_from_title,
    _period_from_title,
    _signed_percent,
    _value_from_text,
)
from bond_futures_monitor.collectors.treasury_calendar import parse_treasury_notice


def test_nbs_release_parsers_cover_regular_transition_and_pmi_wording():
    assert _indicator_from_title("2025年11月份工业生产者出厂价格环比继续上涨") == "PPI_YOY"
    assert _indicator_from_title("解读：2025年11月份工业生产者出厂价格环比继续上涨") is None
    assert _indicator_from_title("2026年7月份居民消费价格同比上涨0.5%") == "CPI_YOY"
    assert _period_from_title("2026年7月份居民消费价格同比上涨0.5%") == "2026-07"
    assert _signed_percent("全国居民消费价格同比下降 0.2%") == pytest.approx(-0.2)
    assert _signed_percent("同比由上月下降 0.9% 转为上涨 0.5%") == pytest.approx(0.5)
    assert _value_from_text("制造业采购经理指数（ PMI ）为 49.8%", "PMI_MFG") == pytest.approx(49.8)


def test_mof_notice_parser_extracts_coupon_bond_fields():
    text = (
        "本期国债为10年期固定利率附息债。"
        "本期国债竞争性招标面值总额900亿元。"
        "（一）招标时间。2026年8月14日上午10:35至11:35。"
    )
    assert parse_treasury_notice(text) == {
        "auction_date": "2026-08-14",
        "tenor": "10Y",
        "planned_amount": 900.0,
    }


def test_mof_notice_parser_extracts_discount_bond_fields():
    text = (
        "本期国债为期限91天的贴现债。"
        "竞争性招标面值总额500亿元。"
        "招标时间。2026年9月3日上午10:35至11:35。"
    )
    assert parse_treasury_notice(text) == {
        "auction_date": "2026-09-03",
        "tenor": "91D",
        "planned_amount": 500.0,
    }

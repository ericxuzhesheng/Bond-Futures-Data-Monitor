from bond_futures_monitor.ai.schema import AFFECTED_MATURITIES, BOND_IMPACTS, CONTRACTS, EVENT_TYPES
from bond_futures_monitor.ai.text_signal import classify_news_item


def test_rule_based_text_signal_output_schema():
    signal = classify_news_item(
        {
            "id": 1,
            "date": "2026-06-08",
            "title": "PBOC injects liquidity",
            "content": "Funding rates moved lower after liquidity injection.",
        }
    )
    assert signal["event_type"] in EVENT_TYPES
    assert signal["bond_impact"] in BOND_IMPACTS
    assert signal["affected_maturity"] in AFFECTED_MATURITIES
    assert set(signal["related_contracts"]).issubset(CONTRACTS)
    assert 1 <= signal["confidence"] <= 5
    assert signal["reasoning"]


def test_rule_based_text_signal_uses_original_title_for_specific_outputs():
    first = classify_news_item(
        {
            "id": 1,
            "date": "2026-06-08",
            "title": "国家发改委将安排超长期特别国债资金支持城市地下管网建设",
            "content": "超长期特别国债资金将对城市地下管网建设改造项目予以加力支持。",
        }
    )
    second = classify_news_item(
        {
            "id": 2,
            "date": "2026-06-08",
            "title": "财政部保持较大力度支持城市更新",
            "content": "财政政策继续发力，实施好税收支持政策。",
        }
    )
    assert "国家发改委" in first["summary"]
    assert "财政部" in second["summary"]
    assert first["summary"] != second["summary"]
    assert first["reasoning"] != second["reasoning"]

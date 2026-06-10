import pytest

from bond_futures_monitor.ai.schema import AFFECTED_MATURITIES, BOND_IMPACTS, CONTRACTS, EVENT_TYPES
from bond_futures_monitor.ai.text_signal import _safe_confidence, classify_news_item, validate_signal


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


def test_safe_confidence_handles_unexpected_llm_values():
    assert _safe_confidence(4) == 4
    assert _safe_confidence("3") == 3
    assert _safe_confidence(3.7) == 3
    assert _safe_confidence(None) == 2
    assert _safe_confidence("high") == 2
    assert _safe_confidence(99) == 5
    assert _safe_confidence(-1) == 1


def test_validate_signal_requires_news_id():
    signal = {
        "news_id": None,
        "date": "2026-06-08",
        "event_type": "other",
        "summary": "x",
        "bond_impact": "neutral",
        "affected_maturity": "unclear",
        "related_contracts": [],
        "confidence": 2,
        "reasoning": "x",
        "model_name": "test",
    }
    with pytest.raises(ValueError, match="news_id"):
        validate_signal(signal)
    signal["news_id"] = 1
    validate_signal(signal)

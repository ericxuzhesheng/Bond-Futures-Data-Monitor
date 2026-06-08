from bond_futures_monitor.ai.schema import AFFECTED_MATURITIES, BOND_IMPACTS, CONTRACTS, EVENT_TYPES
from bond_futures_monitor.ai.text_signal import classify_news_item


def test_mock_ai_text_signal_output_schema():
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

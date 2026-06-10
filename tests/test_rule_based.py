from bond_futures_monitor.signals.rule_based import generate_market_signal


EXPECTED_CATEGORIES = {"利率方向", "曲线形态", "资金面", "公开市场操作", "期货量价", "文本信号", "宏观基本面"}


def test_rule_based_scoring_bullish():
    signal = generate_market_signal(
        {
            "date": "2026-06-08",
            "yield_10y_change": -0.02,
            "dr007_change": -0.05,
            "omo_net_injection_amount": 800,
            "avg_futures_return": 0.001,
            "avg_volume_change": 0.1,
            "avg_ai_sentiment_score": 1,
            "spread_10y_2y": 0.4,
            "spread_30y_10y": 0.2,
            "details": {"macro_indicators": {"PMI_MFG": 49.2}},
        }
    )
    assert signal["market_view"] == "bullish"
    assert signal["total_score"] > 0
    assert set(signal["details"]["score_summary"]) == EXPECTED_CATEGORIES
    assert "利率方向" in signal["details"]["score_summary"]


def test_rule_based_scoring_bearish():
    signal = generate_market_signal(
        {
            "date": "2026-06-08",
            "yield_10y_change": 0.02,
            "dr007_change": 0.05,
            "omo_net_injection_amount": -800,
            "avg_futures_return": -0.001,
            "avg_volume_change": 0.1,
            "avg_ai_sentiment_score": -1,
            "spread_10y_2y": 0.4,
            "spread_30y_10y": 0.2,
        }
    )
    assert signal["market_view"] == "bearish"
    assert signal["total_score"] < 0


def test_rule_based_scoring_exposes_zero_score_dimensions():
    signal = generate_market_signal(
        {
            "date": "2026-06-08",
            "yield_10y_change": 0.001,
            "dr007_change": 0.001,
            "omo_net_injection_amount": 100,
            "avg_futures_return": 0.001,
            "avg_volume_change": -0.1,
            "avg_ai_sentiment_score": 0,
            "spread_10y_2y": 0.4,
            "spread_30y_10y": 0.5,
            "details": {"macro_indicators": {"PMI_MFG": 50.1}},
        }
    )
    assert set(signal["details"]["score_summary"]) == EXPECTED_CATEGORIES
    assert all(item["score"] == 0 for item in signal["details"]["score_items"])
    assert any("DR007" not in note for note in signal["risk_notes"])

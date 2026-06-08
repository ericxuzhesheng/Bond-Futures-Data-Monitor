from bond_futures_monitor.signals.rule_based import generate_market_signal


def test_rule_based_scoring_bullish():
    signal = generate_market_signal(
        {
            "date": "2026-06-08",
            "yield_10y_change": -0.02,
            "dr007_change": -0.05,
            "avg_futures_return": 0.001,
            "avg_volume_change": 0.1,
            "avg_ai_sentiment_score": 1,
            "spread_30y_10y": 0.2,
        }
    )
    assert signal["market_view"] == "bullish"
    assert signal["total_score"] > 0


def test_rule_based_scoring_bearish():
    signal = generate_market_signal(
        {
            "date": "2026-06-08",
            "yield_10y_change": 0.02,
            "dr007_change": 0.05,
            "avg_futures_return": -0.001,
            "avg_volume_change": 0.1,
            "avg_ai_sentiment_score": -1,
            "spread_30y_10y": 0.2,
        }
    )
    assert signal["market_view"] == "bearish"
    assert signal["total_score"] < 0

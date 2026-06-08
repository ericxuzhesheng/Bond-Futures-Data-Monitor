from bond_futures_monitor.cli import run_daily_pipeline
from bond_futures_monitor.database import connect, init_db
from bond_futures_monitor.features.daily_features import build_daily_features


def test_daily_report_generation(tmp_path):
    db_path = tmp_path / "monitor.db"
    report_dir = tmp_path / "reports"
    with connect(db_path) as conn:
        init_db(conn)
        run_daily_pipeline(conn, "2026-06-08", False, report_dir)

    report_path = report_dir / "2026-06-08_daily_report.md"
    content = report_path.read_text(encoding="utf-8")
    assert report_path.exists()
    assert "每日市场判断" in content
    assert "评分拆解" in content
    assert "特征面板" in content
    assert "数据源与质量" in content
    assert "国债期货概览" in content
    assert "AI 政策与新闻解读" in content
    assert "数据质量提示" in content


def test_features_use_latest_ai_signal_per_news_item(tmp_path):
    db_path = tmp_path / "monitor.db"
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO policy_news (id, date, title, source, content, url, data_source)
            VALUES (1, '2026-06-08', 'test', 'source', 'content', NULL, 'tushare_news_cls')
            """
        )
        conn.execute(
            """
            INSERT INTO ai_text_signals
            (news_id, date, event_type, summary, bond_impact, affected_maturity,
             related_contracts, confidence, reasoning, model_name)
            VALUES
            (1, '2026-06-08', 'other', 'old', 'bullish', 'unclear', '[]', 2, 'old', 'mock-rule-based-text-signal-v1'),
            (1, '2026-06-08', 'other', 'new', 'bearish', 'unclear', '[]', 2, 'new', 'rule-based-text-signal-v2')
            """
        )
        conn.commit()

        features = build_daily_features(conn, "2026-06-08")

    assert features["avg_ai_sentiment_score"] == -1
    assert features["details"]["ai_signal_count"] == 1

from bond_futures_monitor.ai.text_signal import classify_news_item
from bond_futures_monitor.database import (
    connect,
    init_db,
    insert_ai_text_signal,
    insert_bond_yields,
    insert_funding_rates,
    insert_futures_quotes,
    insert_macro_indicators,
    insert_open_market_operations,
    insert_policy_news,
    log_run,
    upsert_daily_features,
    upsert_daily_market_signal,
)
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.daily_report import generate_daily_report
from bond_futures_monitor.signals.rule_based import generate_market_signal
from bond_futures_monitor.validation import validate_real_data_coverage


RUN_DATE = "2026-06-08"


def seed_real_source_rows(conn, run_date: str = RUN_DATE) -> None:
    insert_futures_quotes(
        conn,
        [
            {
                "date": run_date,
                "contract": contract,
                "close_price": close,
                "daily_return": ret,
                "volume": volume,
                "open_interest": oi,
                "data_source": f"akshare_cffex_daily:{run_date.replace('-', '')}",
            }
            for contract, close, ret, volume, oi in [
                ("TS", 101.0, 0.001, 1000, 2000),
                ("TF", 102.0, 0.001, 1000, 2000),
                ("T", 103.0, 0.001, 1000, 2000),
                ("TL", 104.0, 0.001, 1000, 2000),
            ]
        ],
    )
    insert_bond_yields(
        conn,
        [
            {"date": run_date, "tenor": tenor, "yield_value": value, "data_source": "tushare_yc_cb:20260608"}
            for tenor, value in [("1Y", 1.4), ("2Y", 1.5), ("5Y", 1.7), ("10Y", 1.9), ("30Y", 2.2)]
        ],
    )
    insert_funding_rates(
        conn,
        [
            {"date": run_date, "rate_name": name, "rate_value": value, "data_source": "tushare_repo_daily:20260608"}
            for name, value in [("DR001", 1.3), ("DR007", 1.5), ("R007", 1.7)]
        ]
        + [
            {"date": run_date, "rate_name": "SHIBOR_ON", "rate_value": 1.31, "data_source": "tushare_shibor:20260608"},
            {"date": run_date, "rate_name": "SHIBOR_7D", "rate_value": 1.55, "data_source": "tushare_shibor:20260608"},
        ],
    )
    insert_open_market_operations(
        conn,
        [
            {
                "date": run_date,
                "operation_type": "reverse_repo",
                "tenor_days": 7,
                "operation_amount": 100.0,
                "maturity_amount": 50.0,
                "net_injection_amount": 50.0,
                "operation_rate": 1.4,
                "source_title": "央行开展100亿元7天期逆回购操作",
                "data_source": f"tushare_news_cls:{run_date}",
            }
        ],
    )
    insert_macro_indicators(
        conn,
        [
            {
                "date": run_date,
                "indicator": indicator,
                "value": value,
                "period": period,
                "data_source": data_source,
            }
            for indicator, value, period, data_source in [
                ("LPR_1Y", 3.0, "2026-05-20", "tushare_shibor_lpr:20260520"),
                ("LPR_5Y", 3.5, "2026-05-20", "tushare_shibor_lpr:20260520"),
                ("CPI_YOY", 0.5, "2026-05", "tushare_cn_cpi:202605"),
                ("PPI_YOY", -2.1, "2026-05", "tushare_cn_ppi:202605"),
                ("PMI_MFG", 49.2, "2026-05", "tushare_cn_pmi:202605"),
            ]
        ],
    )
    insert_policy_news(
        conn,
        [
            {
                "date": run_date,
                "title": "央行公开市场净投放呵护流动性",
                "source": "财联社",
                "content": "资金利率回落，银行间流动性保持合理充裕。",
                "url": "",
                "data_source": "tushare_news_cls:2026-06-08",
            },
            {
                "date": run_date,
                "title": "财政部安排超长期特别国债资金支持城市更新",
                "source": "财联社",
                "content": "超长期特别国债资金将加力支持公共安全和民生保障类工程。",
                "url": "",
                "data_source": "tushare_news_cls:2026-06-08",
            },
        ],
    )


def test_daily_report_generation(tmp_path):
    db_path = tmp_path / "monitor.db"
    report_dir = tmp_path / "reports"
    with connect(db_path) as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        validate_real_data_coverage(conn, RUN_DATE)
        for row in conn.execute("SELECT * FROM policy_news WHERE date = ?", (RUN_DATE,)).fetchall():
            insert_ai_text_signal(conn, classify_news_item(dict(row)))
        features = build_daily_features(conn, RUN_DATE)
        upsert_daily_features(conn, features)
        upsert_daily_market_signal(conn, generate_market_signal(features))
        log_run(conn, RUN_DATE, "success", "Daily real-data pipeline completed")
        report_path = generate_daily_report(conn, RUN_DATE, report_dir)

    content = report_path.read_text(encoding="utf-8")
    assert report_path.exists()
    assert "每日市场判断" in content
    assert "数据真实性检查" in content
    assert "## 公开市场操作概览" in content
    assert "公开市场操作利率" not in content
    assert "| 类型 | 期限 | 投放 | 到期 | 净投放 | 来源标题 |" in content
    assert "当日真实数据合计" in content
    assert "国债期货概览" in content
    assert "政策与新闻结构化解读" in content
    assert "原始标题：央行公开市场净投放呵护流动性" in content
    assert "原始标题：财政部安排超长期特别国债资金支持城市更新" in content
    assert "数据库写入结果" in content
    assert "open_market_operations: 1 rows" in content
    assert "run_status: success" in content
    assert "## 宏观基本面概览" in content
    assert "| 制造业 PMI | 49.20 | 2026-05 |" in content
    assert "| LPR 1年期 | 3.00% | 2026-05-20 |" in content
    assert "macro_indicators: 5 rows" in content
    for category in ["利率方向", "曲线形态", "资金面", "公开市场操作", "期货量价", "文本信号", "宏观基本面"]:
        assert f"| {category} |" in content
    assert "sample" not in content.lower()


def test_features_use_latest_ai_signal_per_news_item(tmp_path):
    db_path = tmp_path / "monitor.db"
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO policy_news (id, date, title, source, content, url, data_source)
            VALUES (1, '2026-06-08', 'test', 'source', 'content', NULL, 'tushare_news_cls:2026-06-08')
            """
        )
        conn.execute(
            """
            INSERT INTO ai_text_signals
            (news_id, date, event_type, summary, bond_impact, affected_maturity,
             related_contracts, confidence, reasoning, model_name)
            VALUES
            (1, '2026-06-08', 'other', 'old', 'bullish', 'unclear', '[]', 2, 'old', 'rule-based-text-signal-v3'),
            (1, '2026-06-08', 'other', 'new', 'bearish', 'unclear', '[]', 2, 'new', 'rule-based-text-signal-v4')
            """
        )
        conn.commit()

        features = build_daily_features(conn, "2026-06-08")

    assert features["avg_ai_sentiment_score"] == -1
    assert features["details"]["ai_signal_count"] == 1

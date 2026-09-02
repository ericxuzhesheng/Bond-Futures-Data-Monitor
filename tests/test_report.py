import pytest

from bond_futures_monitor.ai.text_signal import classify_news_item
from bond_futures_monitor.database import (
    connect,
    init_db,
    insert_ai_text_signal,
    insert_bond_yields,
    insert_funding_rates,
    insert_futures_quotes,
    insert_macro_indicators,
    insert_macro_history,
    insert_open_market_operations,
    insert_policy_news,
    insert_treasury_issuance_calendar,
    insert_yield_curve_comparisons,
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
    insert_macro_history(
        conn,
        [
            {
                "date": run_date,
                "indicator": indicator,
                "period": period,
                "value": value,
                "release_date": run_date,
                "source_url": "https://www.stats.gov.cn/sj/zxfb/test.html",
                "data_source": "nbs_official_release",
            }
            for period, cpi, ppi, pmi in [
                ("2026-05", 0.5, -2.1, 49.2),
                ("2026-04", 0.3, -2.5, 49.0),
                ("2026-03", 0.1, -2.7, 50.1),
                ("2026-02", -0.2, -2.8, 49.5),
                ("2026-01", 0.0, -2.9, 49.3),
                ("2025-12", 0.2, -2.6, 50.0),
            ]
            for indicator, value in (("CPI_YOY", cpi), ("PPI_YOY", ppi), ("PMI_MFG", pmi))
        ],
    )
    insert_treasury_issuance_calendar(
        conn,
        [{
            "date": run_date,
            "auction_date": "2026-06-09",
            "title": "关于2026年记账式附息国债发行工作有关事宜的通知",
            "tenor": "10Y",
            "planned_amount": 900.0,
            "source_url": "https://www.mof.gov.cn/test.html",
            "data_source": "mof_official_notice",
        }],
    )
    insert_yield_curve_comparisons(
        conn,
        [
            {
                "date": run_date,
                "observation_date": run_date,
                "tenor": tenor,
                "chinabond_yield": value,
                "cfets_yield": value + 0.001,
                "deviation_bp": 0.1,
                "chinabond_source": f"akshare_chinabond_curve:{run_date}",
                "cfets_source": f"akshare_chinamoney_cfets_curve:{run_date}",
            }
            for tenor, value in (("1Y", 1.4), ("3Y", 1.6), ("5Y", 1.7), ("10Y", 1.9), ("30Y", 2.2))
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
    assert content.startswith("# 国债期货日报\n")
    assert "## 当日简评" in content
    assert "DR007 为 1.500%" in content
    assert "公开市场操作利率" in content
    assert "| 类型 | 期限 | 投放 | 到期 | 净投放 |" in content
    assert "| 期限 | 收益率 | 较上一观测日 |" in content
    assert "| 指标 | 利率 | 较上一观测日 |" in content
    assert "央行公开市场净投放呵护流动性" in content
    assert "财政部安排超长期特别国债资金支持城市更新" in content
    assert "run_status: success" in content
    assert "| 制造业 PMI | 49.20 | 2026-05 |" in content
    assert "| LPR 1年期 | 3.00% | 2026-05-20 |" in content
    assert "| 2026-05 | 0.5% | -2.1% | 49.2 |" in content
    assert "| 2026-06-09 | 10Y | 900 亿元 |" in content
    assert "| 10Y | 1.9000% | 1.9010% | +0.10 bp | 2026-06-08 |" in content
    assert "macro_history: 18" in content
    assert "treasury_issuance_calendar: 1" in content
    assert "yield_curve_comparisons: 5" in content
    for category in ["利率方向", "曲线形态", "资金面", "公开市场操作", "期货量价", "文本信号", "宏观基本面"]:
        assert f"| {category} |" in content
    assert content.count("<details>") == content.count("</details>") == 5
    assert content.index("## 期货表现") < content.index("futures_20d.svg") < content.index("## 利率与资金")
    assert content.index("### 资金利率") < content.index("funding_20d.svg") < content.index("## 宏观与后续观察")
    assert "## 30秒执行摘要" not in content
    assert "## 每日市场判断" not in content
    assert content.index("tushare_yc_cb:") > content.index("## 方法与数据附录")
    assert "—" not in content
    assets = report_dir / "assets"
    assert len(list(assets.glob(f"{RUN_DATE}_*.svg"))) == 4


def test_missing_calendar_is_not_reported_as_zero_issuance(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        conn.execute("DELETE FROM treasury_issuance_calendar")
        features = build_daily_features(conn, RUN_DATE)
        upsert_daily_market_signal(conn, generate_market_signal(features))
        before = conn.total_changes
        path = generate_daily_report(conn, RUN_DATE, tmp_path / "reports")
        assert conn.total_changes == before
    content = path.read_text(encoding="utf-8")
    assert "发行规模和净融资暂不列数" in content
    assert "计划发行额：0" not in content
    assert "### 政策与新闻" not in content


def test_chart_series_share_the_same_date_positions():
    from bond_futures_monitor.reports.charts import _svg_chart_body
    import xml.etree.ElementTree as ET
    body = _svg_chart_body(760, 360, "测试", {
        "完整": [("08-28", 1.0), ("08-31", 1.1), ("09-01", 1.2)],
        "短序列": [("09-01", 1.3)],
    }, 45)
    root = ET.fromstring("<svg>" + body + "</svg>")
    lines = root.findall("polyline")
    assert lines[0].attrib["points"].split()[-1].split(",")[0] == lines[1].attrib["points"].split(",")[0]
    assert root.findall("circle")


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


def test_features_label_fdr007_as_the_funding_anchor(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        for weighted, fixing in (("DR001", "FDR001"), ("DR007", "FDR007"), ("R007", "FR007")):
            conn.execute(
                "UPDATE funding_rates SET rate_name = ? WHERE date = ? AND rate_name = ?",
                (fixing, RUN_DATE, weighted),
            )
        features = build_daily_features(conn, RUN_DATE)

    funding = features["details"]["feature_groups"]["funding"]
    assert funding["funding_anchor_name"] == "FDR007"
    assert funding["repo_7d_spread"] == pytest.approx(0.2)


def test_fixing_anchor_does_not_switch_when_weighted_quotes_appear(tmp_path):
    from bond_futures_monitor.reports.daily_report import _multi_horizon_rows
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        insert_funding_rates(conn, [
            {"date": day, "rate_name": name, "rate_value": value, "data_source": "fixing"}
            for day, delta in (("2026-06-05", -.01), (RUN_DATE, 0))
            for name, value in (("FDR007", 1.4 + delta), ("FR007", 1.6 + delta))])
        features = build_daily_features(conn, RUN_DATE)
        funding = features["details"]["feature_groups"]["funding"]
        assert funding["funding_anchor_name"] == "FDR007"
        assert features["dr007_change"] == pytest.approx(.01)
        assert funding["repo_7d_spread"] == pytest.approx(.2)
        assert "DR007" in funding["available_rates"]
        assert any("| FDR007 |" in row for row in _multi_horizon_rows(conn, RUN_DATE))


def test_funding_chart_uses_20_dates_not_100_rows(tmp_path):
    from datetime import date, timedelta
    import xml.etree.ElementTree as ET
    from bond_futures_monitor.reports.charts import _funding_chart
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        insert_funding_rates(conn, [
            {"date": (date(2025, 12, 17) + timedelta(days=i)).isoformat(), "rate_name": name,
             "rate_value": 1.4, "data_source": "test-real-source"}
            for i in range(20)
            for name in ("FDR001", "FDR007", "FR007", "SHIBOR_ON", "SHIBOR_7D", "DR001", "DR007", "R007")])
        path = _funding_chart(conn, "2026-01-05", tmp_path)
        lines = list(ET.parse(path).iter("{http://www.w3.org/2000/svg}polyline"))
        assert len(lines) == 5
        assert all(len(line.attrib["points"].split()) == 20 for line in lines)


def test_activity_horizons_use_trading_observations_and_exclude_future(tmp_path):
    from bond_futures_monitor.reports.daily_report import _multi_horizon_rows
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        for day, volume in (("2025-12-25", 230466), ("2025-12-26", 260316),
                            ("2025-12-29", 396087), ("2025-12-30", 264620),
                            ("2025-12-31", 316443), ("2026-01-05", 283295),
                            ("2026-01-06", 999999)):
            insert_futures_quotes(conn, [{"date": day, "contract": "T", "close_price": 100,
                "daily_return": .001, "volume": volume, "open_interest": volume * 2,
                "data_source": "real-source"}])
        rows = _multi_horizon_rows(conn, "2026-01-05")
    assert "| 总成交量 | 283,295 | -10.5% | +22.9% | 67% |" in rows
    assert "| 总持仓量 | 566,590 | -10.5% | +22.9% | 67% |" in rows


@pytest.mark.parametrize("values,periods,expected", [
    ([100], 1, "样本不足（需2次观测）"),
    ([100] * 5, 5, "样本不足（需6次观测）"),
    ([0, 100], 1, "基期为0或负值，不可比"),
    ([100, 0], 1, "-100.0%"),
    ([100] * 6, 5, "+0.0%"),
])
def test_relative_change_explains_unavailable_values(values, periods, expected):
    from bond_futures_monitor.reports.daily_report import _relative_change
    assert _relative_change(values, periods) == expected


@pytest.mark.parametrize("bad_cell", ["缺失", "—", "", "None", "NaN%", "-inf", "N/A"])
def test_report_quality_gate_preserves_previous_report(tmp_path, monkeypatch, bad_cell):
    import bond_futures_monitor.reports.daily_report as report
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        upsert_daily_market_signal(conn, generate_market_signal(build_daily_features(conn, RUN_DATE)))
        target = tmp_path / f"{RUN_DATE}_daily_report.md"
        target.write_text("previous complete report", encoding="utf-8")
        monkeypatch.setattr(report, "_multi_horizon_rows", lambda *_: [f"| 总成交量 | 100 | 0% | {bad_cell} | 50% |"])
        with pytest.raises(ValueError, match="Unexplained report cell"):
            generate_daily_report(conn, RUN_DATE, tmp_path)
        assert target.read_text(encoding="utf-8") == "previous complete report"


def test_macro_gaps_and_optional_fields_have_reasons():
    from bond_futures_monitor.reports.daily_report import (
        _macro_history_table_rows, _feature_panel_rows, _format_bp_change,
        _format_tenor, validate_report_tables,
    )
    rows = _macro_history_table_rows([{"period": "2025-12", "indicator": "PMI_MFG", "value": 50.1}])
    assert rows == ["| 2025-12 | 截至当日未取得发布值 | 截至当日未取得发布值 | 50.1 |"]
    rows += _feature_panel_rows({"open_market_operations": {"operation_count": 0, "omo_operation_rate": None}})
    assert any("未取得完整操作记录" in row for row in rows)
    assert _format_bp_change(1.5, None) == "无前一观测日同口径记录"
    assert _format_tenor(None) == "原始记录未注明期限"
    assert validate_report_tables("\n".join(rows)) > 0


def test_report_validator_leaves_source_prose_unchanged():
    from bond_futures_monitor.reports.daily_report import validate_report_tables
    content = "原文—说明\n```text\n| 缺失 |\n```\n| 状态 | 未参与评分 |\n"
    assert validate_report_tables(content) == 2


def test_news_scope_repair_is_scoped_and_recoverable(tmp_path):
    import json
    from scripts.repair_omo_news_scope import repair
    (tmp_path / "data" / f"backfill_2026_{RUN_DATE}").mkdir(parents=True)
    output = tmp_path / "reports_output"
    output.mkdir()
    (output / "backfill_2026_manifest.json").write_text(
        json.dumps({"completed": [RUN_DATE], "end": RUN_DATE}), encoding="utf-8")
    database = tmp_path / "data/bond_futures_monitor.db"
    title = "下周央行公开市场将有100亿元逆回购到期"
    with connect(database) as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        insert_policy_news(conn, [{"date": RUN_DATE, "title": title, "content": title,
            "url": "", "source": "财联社", "data_source": f"tushare_news_cls:{RUN_DATE}"}])
        insert_open_market_operations(conn, [{"date": RUN_DATE, "operation_type": "reverse_repo",
            "tenor_days": None, "operation_amount": 0, "maturity_amount": 100,
            "net_injection_amount": -100, "operation_rate": None, "source_title": title,
            "data_source": f"tushare_news_cls:{RUN_DATE}"}])
    assert len(repair(tmp_path)["removed_records"]) == 1
    with connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM open_market_operations").fetchone()[0] == 2
    assert repair(tmp_path, apply=True)["affected_dates"] == [RUN_DATE]
    with connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM open_market_operations").fetchone()[0] == 1
        assert conn.execute("SELECT omo_net_injection_amount FROM daily_features").fetchone()[0] == 50
    with connect(tmp_path / "data" / f"backfill_2026_{RUN_DATE}" / "before_report_cell_repair.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM open_market_operations").fetchone()[0] == 2
    assert (output / "2026_omo_scope_repair.json").exists()
    manifest = json.loads((output / "backfill_2026_manifest.json").read_text(encoding="utf-8"))
    assert manifest["missing_optional_dates"]["open_market_operations"] == []

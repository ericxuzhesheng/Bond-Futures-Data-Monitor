from bond_futures_monitor.cli import run_daily_pipeline
from bond_futures_monitor.database import connect, init_db


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

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bond_futures_monitor import backfill
from bond_futures_monitor import database as db


def test_end_excludes_future_and_intraday():
    now = datetime(2026, 9, 2, 14, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert backfill.closed_end(2026, now) == "2026-09-01"
    assert backfill.closed_end(2025, now) == "2025-12-31"
    with pytest.raises(ValueError, match="future"):
        backfill.closed_end(2027, now)


def test_macro_uses_publication_date_not_observation_month():
    releases = [
        {"indicator": name, "period": period, "value": value, "release_date": released,
         "source_url": "https://www.stats.gov.cn/release", "data_source": "nbs_official_release"}
        for name in ("CPI_YOY", "PPI_YOY", "PMI_MFG")
        for period, value, released in (("2025-11", 1, "2025-12-10"), ("2025-12", 2, "2026-01-10"))
    ]
    lpr = pd.DataFrame([{"TRADE_DATE": "2025-12-20", "LPR1Y": 3.0, "LPR5Y": 3.5},
                        {"TRADE_DATE": "2026-01-20", "LPR1Y": 2.9, "LPR5Y": 3.4}])
    # PMI's test value must be within its separately validated range.
    for row in releases:
        if row["indicator"] == "PMI_MFG":
            row["value"] += 48
    rows = backfill.macro_rows(releases, lpr, "2026-01-05")
    monthly = [r for r in rows if not r["indicator"].startswith("LPR")]
    assert {r["period"] for r in monthly} == {"2025-11"}
    assert all("2025-12-10" in r["data_source"] for r in monthly)
    assert rows[0]["period"] == "2025-12-20"
    assert {r["period"] for r in backfill.release_rows(releases, "2026-01-10", 1)} == {"2025-12"}
    with pytest.raises(RuntimeError, match="Missing point-in-time"):
        backfill.macro_rows([], lpr, "2026-01-05")


def test_cache_reuses_success_but_not_empty(tmp_path):
    cache = backfill.Cache(tmp_path)
    assert cache.rows("good", lambda: [{"value": 1}]) == [{"value": 1}]
    assert cache.rows("good", lambda: pytest.fail("must not fetch again")) == [{"value": 1}]
    with pytest.raises(RuntimeError, match="No historical"):
        cache.rows("empty", lambda: [])
    assert not (tmp_path / "empty.json").exists()


def test_failed_historical_rebuild_preserves_snapshot(monkeypatch, tmp_path):
    with db.connect(tmp_path / "test.db") as conn:
        db.init_db(conn)
        original = {"date": "2026-01-05", "contract": "T", "close_price": 100, "daily_return": .01,
                    "volume": 100, "open_interest": 200, "data_source": "real-source"}
        db.insert_futures_quotes(conn, [original])
        conn.commit()
        def collect(conn, *_):
            db.insert_futures_quotes(conn, [dict(original, close_price=105)])
        monkeypatch.setattr(backfill, "collect_missing", collect)
        with pytest.raises(RuntimeError, match="Missing point-in-time"):
            backfill.rebuild_day(conn, None, {"releases": [], "lpr": pd.DataFrame()}, "2026-01-05")
        assert conn.execute("SELECT close_price FROM futures_quotes").fetchone()[0] == 100


def test_first_day_report_does_not_invent_five_day_return_or_average(tmp_path):
    from bond_futures_monitor.reports.daily_report import _futures_position_rows, _multi_horizon_rows
    with db.connect(tmp_path / "first.db") as conn:
        db.init_db(conn)
        db.insert_futures_quotes(conn, [{"date": "2026-01-05", "contract": "T", "close_price": 100,
            "daily_return": .001, "volume": 100, "open_interest": 200, "data_source": "real-source"}])
        assert "| 缺失 | 缺失 | 数据不足 |" in _futures_position_rows(conn, "2026-01-05")[0]
        assert "| 期货平均收益 | +0.100% | +0.100% | 缺失 |" in "\n".join(_multi_horizon_rows(conn, "2026-01-05"))


def test_chinabond_fallback_is_exact_date_and_labels_interpolation(tmp_path):
    cache = backfill.Cache(tmp_path)
    cache.rows("chinabond_2026-01", lambda: [
        {"日期": "2026-01-05", "曲线名称": "中债国债收益率曲线", "1年": 1.2,
         "3年": 1.4, "5年": 1.5, "10年": 1.8, "30年": 2.2}])
    shared = {"dates": ["2026-01-05", "2026-01-06"], "cfets_unavailable_months": {"2026-01"}}
    rows = backfill.historical_yields(cache, shared, "2026-01-05")
    two = next(r for r in rows if r["tenor"] == "2Y")
    assert two["yield_value"] == pytest.approx(1.3)
    assert "interpolated_1y_3y" in two["data_source"]
    with pytest.raises(RuntimeError, match="No same-day"):
        backfill.historical_yields(cache, shared, "2026-01-06")


def test_omo_ignores_unsupported_notice_but_requires_maturity(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import requests

    cache = backfill.Cache(tmp_path)
    listing = "<table>" + "".join(
        f'<tr><td><a href="https://www.pbc.gov.cn/{name}">公开市场业务交易公告 [2026]第1号</a> {day}</td></tr>'
        for name, day in (("mlf", "2026-01-12"), ("repo", "2026-01-12"), ("prior", "2026-01-05"), ("old", "2025-10-01"))
    ) + "</table>"
    cache.rows("pbc_list_1", lambda: [listing])
    def get(url, **_):
        text = "央行开展中期借贷便利操作" if url.endswith("mlf") else (
            "央行开展50亿元7天期逆回购操作，操作利率1.4%" if url.endswith("prior") else
            "央行开展100亿元7天期逆回购操作，操作利率1.4%")
        return SimpleNamespace(text=text, raise_for_status=lambda: None)
    monkeypatch.setattr(requests, "Session", lambda: SimpleNamespace(get=get))
    result = backfill.historical_omo(cache, ["2026-01-12", "2026-01-05"])
    assert result["2026-01-12"][0]["net_injection_amount"] == 50
    assert result["2026-01-05"] == []

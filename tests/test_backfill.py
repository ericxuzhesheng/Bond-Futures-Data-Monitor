from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bond_futures_monitor import backfill
from bond_futures_monitor import database as db


def test_warmup_uses_trading_sessions_and_keeps_year_separate():
    dates = list(pd.bdate_range("2025-01-01", "2026-01-05").strftime("%Y-%m-%d"))
    prior, reports = backfill.split_calendar(dates, "2026-01-01")
    assert len(prior) == 120 and all(d < "2026-01-01" for d in prior)
    assert all(d >= "2026-01-01" for d in reports)
    assert not set(prior) & set(reports)
    with pytest.raises(RuntimeError, match="120 prior"):
        backfill.split_calendar(dates[-50:], "2026-01-01")


def test_warmup_failure_blocks_report_generation(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backfill, "get_settings", lambda: SimpleNamespace(
        database_path=tmp_path / "test.db", reports_output_dir=tmp_path / "reports"))
    monkeypatch.setattr(backfill, "prepare", lambda *_: {
        "dates": ["2026-01-05"], "warmup_dates": ["2025-12-31"]})
    monkeypatch.setattr(backfill, "historical_omo", lambda *_: {})
    def fail(*_, **__):
        raise RuntimeError("missing historical funding")
    monkeypatch.setattr(backfill, "rebuild_day", fail)
    monkeypatch.setattr(backfill, "generate_daily_report", lambda *_: pytest.fail("must not publish"))
    assert backfill.main(["--year", "2026"]) == 1
    manifest = json.loads((tmp_path / "reports/backfill_2026_manifest.json").read_text(encoding="utf-8"))
    assert manifest["warmup_failed"] and not manifest["completed"]


def test_rolling_window_has_60_changes_and_ignores_future(tmp_path):
    from bond_futures_monitor.features.daily_features import build_daily_features
    from bond_futures_monitor.reports.charts import generate_report_charts
    from bond_futures_monitor.reports.daily_report import _multi_horizon_rows
    dates = list(pd.bdate_range(end="2026-01-05", periods=61).strftime("%Y-%m-%d"))
    with db.connect(tmp_path / "test.db") as conn:
        db.init_db(conn)
        for i, day in enumerate(dates):
            db.insert_futures_quotes(conn, [{"date": day, "contract": c, "close_price": 100,
                "daily_return": .001, "volume": 100 + i, "open_interest": 200 + i, "data_source": "source"}
                for c in ("TS", "TF", "T", "TL")])
            db.insert_bond_yields(conn, [{"date": day, "tenor": t, "yield_value": 2 + i * .001,
                "data_source": "source"} for t in ("1Y", "2Y", "5Y", "10Y", "30Y")])
            db.insert_funding_rates(conn, [{"date": day, "rate_name": r, "rate_value": 1 + i * .001,
                "data_source": "source"} for r in ("FDR001", "FDR007", "FR007", "SHIBOR_ON", "SHIBOR_7D")])
        first = build_daily_features(conn, "2026-01-05")
        rolling = first["details"]["rolling_context"]
        assert rolling["yield_change_observations"] == 60
        assert rolling["funding_change_observations"] == 60
        assert rolling["history_days"] == 20
        assert first["yield_10y_change"] == pytest.approx(.001)
        assert "缺失" not in "\n".join(_multi_horizon_rows(conn, "2026-01-05"))
        db.insert_bond_yields(conn, [{"date": "2026-01-06", "tenor": "10Y", "yield_value": 9, "data_source": "future"}])
        assert build_daily_features(conn, "2026-01-05") == first
        paths = generate_report_charts(conn, "2026-01-05", tmp_path)
        chart = paths[0].read_text(encoding="utf-8")
        assert chart.index(">2025-12-") < chart.index(">2026-01-05<")


def test_history_gate_rejects_missing_calendar_session(tmp_path):
    with db.connect(tmp_path / "test.db") as conn:
        db.init_db(conn)
        with pytest.raises(RuntimeError):
            backfill.validate_history_window(conn, ["2025-12-31"] * 60)


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

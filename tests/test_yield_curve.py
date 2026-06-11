"""Yield-curve fallback ordering and AkShare close_return parsing."""

import sys

import pandas as pd

import bond_futures_monitor.collectors.yield_curve as yc


RUN_DATE = "2026-06-08"
TENORS = {"1Y", "2Y", "5Y", "10Y", "30Y"}


def _rows(source: str):
    return [
        {"date": RUN_DATE, "tenor": tenor, "yield_value": 1.5, "data_source": source}
        for tenor in TENORS
    ]


def test_akshare_prefers_close_return(monkeypatch):
    primary = _rows("akshare_bond_china_close_return:x")
    secondary_calls = []
    monkeypatch.setattr(yc, "_collect_akshare_close_return", lambda d: primary)
    monkeypatch.setattr(
        yc, "_collect_akshare_china_yield", lambda d: secondary_calls.append(d) or []
    )

    assert yc._collect_akshare(RUN_DATE) == primary
    assert secondary_calls == []  # secondary not reached when primary succeeds


def test_akshare_falls_back_to_china_yield(monkeypatch):
    secondary = _rows("akshare_bond_china_yield:x")
    monkeypatch.setattr(yc, "_collect_akshare_close_return", lambda d: [])
    monkeypatch.setattr(yc, "_collect_akshare_china_yield", lambda d: secondary)

    out = yc._collect_akshare(RUN_DATE)
    assert out[0]["data_source"].startswith("akshare_bond_china_yield")


def _fake_akshare(df):
    class FakeAk:
        @staticmethod
        def bond_china_close_return(**_kwargs):
            return df

    return FakeAk


def test_close_return_extracts_required_tenors(monkeypatch):
    df = pd.DataFrame(
        {
            "日期": ["2026-06-08"] * 6,
            "期限": [1.0, 2.0, 5.0, 10.0, 30.0, 46.0],
            "到期收益率": [1.19, 1.28, 1.46, 1.75, 2.24, 2.40],
        }
    )
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(df))

    rows = yc._collect_akshare_close_return(RUN_DATE)
    assert {row["tenor"] for row in rows} == TENORS
    assert all(r["data_source"].startswith("akshare_bond_china_close_return") for r in rows)
    by_tenor = {r["tenor"]: r["yield_value"] for r in rows}
    assert by_tenor["10Y"] == 1.75  # 46Y noise row is ignored


def test_close_return_skips_incomplete_curve(monkeypatch):
    # 30Y missing -> never return a partial curve for any backfill offset.
    df = pd.DataFrame(
        {
            "日期": ["2026-06-08"] * 4,
            "期限": [1.0, 2.0, 5.0, 10.0],
            "到期收益率": [1.19, 1.28, 1.46, 1.75],
        }
    )
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(df))

    assert yc._collect_akshare_close_return(RUN_DATE) == []

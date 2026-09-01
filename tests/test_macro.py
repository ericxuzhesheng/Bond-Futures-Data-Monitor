"""Tests for the macro fundamental-indicator collector."""

import math
from datetime import date as Date

import pytest

import bond_futures_monitor.collectors.macro as macro_module
from bond_futures_monitor.collectors.macro import (
    _month_offset,
    _validated_value,
    collect_macro_indicators,
    latest_monthly_value,
)


RUN_DATE = "2026-06-08"


def test_macro_collector_rejects_disabled_live_data():
    with pytest.raises(RuntimeError, match="Sample data is disabled"):
        collect_macro_indicators(RUN_DATE, use_live_data=False)


def test_macro_collector_uses_open_source_without_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    rows = [
        {"date": RUN_DATE, "indicator": name, "value": 1.0, "period": "2026-06", "data_source": "akshare:test"}
        for name in ("LPR_1Y", "LPR_5Y", "CPI_YOY", "PPI_YOY", "PMI_MFG")
    ]
    rows[-1]["value"] = 50.0
    monkeypatch.setattr(macro_module, "_collect_akshare", lambda run_date: rows)
    assert {row["indicator"] for row in collect_macro_indicators(RUN_DATE)} == macro_module.REQUIRED_INDICATORS


def test_validated_value_rejects_implausible_values():
    assert _validated_value("LPR_1Y", "3.0") == 3.0
    assert _validated_value("CPI_YOY", -0.3) == -0.3
    assert _validated_value("PMI_MFG", 49.2) == 49.2
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_value("LPR_1Y", 0.0)
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_value("PMI_MFG", 5.0)
    with pytest.raises(RuntimeError, match="outside the plausible range"):
        _validated_value("CPI_YOY", math.nan)
    with pytest.raises(RuntimeError, match="not numeric"):
        _validated_value("PPI_YOY", None)


def test_latest_monthly_value_picks_latest_non_null_month():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame(
        [
            {"month": "202603", "nt_yoy": 0.1},
            {"month": "202605", "nt_yoy": math.nan},
            {"month": "202604", "nt_yoy": 0.3},
        ]
    )
    value, period = latest_monthly_value(df, ("nt_yoy",))
    assert value == 0.3
    assert period == "202604"


def test_latest_monthly_value_probes_field_candidates():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([{"month": "202605", "pmi": 49.5}])
    value, period = latest_monthly_value(df, ("pmi010000", "pmi", "man_pmi"))
    assert value == 49.5
    assert period == "202605"


def test_latest_monthly_value_matches_uppercase_columns():
    # Tushare cn_pmi returns MONTH/PMI010000 in uppercase.
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([{"MONTH": "202605", "PMI010000": 50.0}])
    value, period = latest_monthly_value(df, ("pmi010000", "pmi", "man_pmi"))
    assert value == 50.0
    assert period == "202605"


def test_latest_monthly_value_fails_loudly_on_unusable_data():
    pd = pytest.importorskip("pandas")
    with pytest.raises(RuntimeError, match="returned no rows"):
        latest_monthly_value(pd.DataFrame(), ("nt_yoy",))
    df_wrong_fields = pd.DataFrame([{"month": "202605", "other": 1.0}])
    with pytest.raises(RuntimeError, match="none of the expected fields"):
        latest_monthly_value(df_wrong_fields, ("nt_yoy",))
    df_all_null = pd.DataFrame([{"month": "202605", "nt_yoy": math.nan}])
    with pytest.raises(RuntimeError, match="no non-null value"):
        latest_monthly_value(df_all_null, ("nt_yoy",))


def test_month_offset_handles_year_boundaries():
    assert _month_offset(Date(2026, 6, 8), -4) == "202602"
    assert _month_offset(Date(2026, 2, 1), -4) == "202510"
    assert _month_offset(Date(2026, 12, 31), 0) == "202612"

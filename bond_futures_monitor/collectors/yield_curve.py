"""China government bond yield curve collector."""

from __future__ import annotations

import os
from datetime import date as Date
from datetime import timedelta


def collect_bond_yields(run_date: str, use_live_data: bool = False) -> list[dict[str, object]]:
    if use_live_data:
        live_rows = _try_collect_tushare(run_date)
        if live_rows:
            return live_rows
    return sample_bond_yields(run_date)


def sample_bond_yields(run_date: str) -> list[dict[str, object]]:
    values = {
        "1Y": 1.58,
        "2Y": 1.69,
        "5Y": 1.87,
        "10Y": 2.02,
        "30Y": 2.22,
    }
    return [
        {"date": run_date, "tenor": tenor, "yield_value": value, "data_source": "sample_fallback"}
        for tenor, value in values.items()
    ]


def _try_collect_tushare(run_date: str) -> list[dict[str, object]]:
    try:
        import tushare as ts  # type: ignore
    except Exception:
        return []

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        return []

    pro = ts.pro_api(token)
    target = Date.fromisoformat(run_date)
    terms = {1.0: "1Y", 2.0: "2Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}
    for offset in range(0, 10):
        query_date = (target - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = pro.yc_cb(ts_code="1001.CB", curve_type="0", trade_date=query_date)
        except Exception:
            return []
        if df.empty:
            continue
        rows = []
        for term, tenor in terms.items():
            matched = df[df["curve_term"].astype(float).round(4) == term]
            if not matched.empty:
                rows.append(
                    {
                        "date": run_date,
                        "tenor": tenor,
                        "yield_value": float(matched.iloc[0]["yield"]),
                        "data_source": f"tushare_yc_cb:{query_date}",
                    }
                )
        if rows:
            return rows
    return []

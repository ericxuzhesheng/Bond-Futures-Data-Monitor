"""China government bond yield curve collector."""

from __future__ import annotations

import os
from datetime import date as Date
from datetime import timedelta


REQUIRED_TENORS = {1.0: "1Y", 2.0: "2Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}


def collect_bond_yields(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect real China government bond yield-curve data from Tushare."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; bond yields must come from a live source.")

    rows = _collect_tushare(run_date)
    available = {row["tenor"] for row in rows}
    required = set(REQUIRED_TENORS.values())
    if available != required:
        raise RuntimeError(
            "Live yield-curve coverage is incomplete: "
            f"expected {sorted(required)}, got {sorted(available) or 'none'} for {run_date}."
        )
    return rows


def _collect_tushare(run_date: str) -> list[dict[str, object]]:
    try:
        import tushare as ts  # type: ignore
    except Exception as exc:
        raise RuntimeError("Tushare is required for China government bond yields.") from exc

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for China government bond yields.")

    pro = ts.pro_api(token)
    target = Date.fromisoformat(run_date)
    for offset in range(0, 10):
        query_date = (target - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = pro.yc_cb(ts_code="1001.CB", curve_type="0", trade_date=query_date)
        except Exception as exc:
            raise RuntimeError(f"Tushare yc_cb failed for {query_date}.") from exc
        if df is None or df.empty:
            continue

        rows = []
        for term, tenor in REQUIRED_TENORS.items():
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

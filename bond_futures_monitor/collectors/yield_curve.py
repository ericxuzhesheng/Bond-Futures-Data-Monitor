"""China government bond yield curve collector."""

from __future__ import annotations

import os
from datetime import date as Date
from datetime import timedelta
from typing import Any

from bond_futures_monitor.retry import retry_call


REQUIRED_TENORS = {1.0: "1Y", 2.0: "2Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}

# Tolerance for matching curve terms returned by the API (in years).
TERM_MATCH_TOLERANCE = 0.01

# Plausible annualized CGB yield range (percent).
MIN_PLAUSIBLE_YIELD = 0.0
MAX_PLAUSIBLE_YIELD = 15.0


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
            df = retry_call(
                lambda query_date=query_date: pro.yc_cb(ts_code="1001.CB", curve_type="0", trade_date=query_date),
                description=f"Tushare yc_cb for {query_date}",
            )
        except Exception as exc:
            raise RuntimeError(f"Tushare yc_cb failed for {query_date}.") from exc
        if df is None or df.empty:
            continue

        rows = _rows_from_curve(df, run_date, query_date)
        if rows:
            return rows
    return []


def _rows_from_curve(df: Any, run_date: str, query_date: str) -> list[dict[str, object]]:
    """Extract required tenor rows from one curve snapshot using tolerant term matching."""

    terms = df["curve_term"].astype(float)
    rows: list[dict[str, object]] = []
    for term, tenor in REQUIRED_TENORS.items():
        matched = df[(terms - term).abs() < TERM_MATCH_TOLERANCE]
        if matched.empty:
            continue
        rows.append(
            {
                "date": run_date,
                "tenor": tenor,
                "yield_value": _validated_yield(tenor, matched.iloc[0]["yield"]),
                "data_source": f"tushare_yc_cb:{query_date}",
            }
        )
    return rows


def _validated_yield(tenor: str, value: object) -> float:
    """Convert a yield value and fail loudly when it is missing or implausible."""

    try:
        yield_value = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Yield for tenor {tenor} is not numeric: {value!r}.") from exc
    # NaN fails both comparisons, so it is rejected here as well.
    if not MIN_PLAUSIBLE_YIELD < yield_value < MAX_PLAUSIBLE_YIELD:
        raise RuntimeError(
            f"Yield for tenor {tenor}={yield_value} is outside the plausible range "
            f"({MIN_PLAUSIBLE_YIELD}, {MAX_PLAUSIBLE_YIELD})."
        )
    return yield_value

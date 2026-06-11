"""China government bond yield curve collector."""

from __future__ import annotations

import logging
import os
import socket
from contextlib import contextmanager
from datetime import date as Date
from datetime import timedelta
from typing import Any

from bond_futures_monitor.retry import retry_call


logger = logging.getLogger(__name__)

REQUIRED_TENORS = {1.0: "1Y", 2.0: "2Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}

# Tolerance for matching curve terms returned by the API (in years).
TERM_MATCH_TOLERANCE = 0.01

# Plausible annualized CGB yield range (percent).
MIN_PLAUSIBLE_YIELD = 0.0
MAX_PLAUSIBLE_YIELD = 15.0

# AkShare interfaces accept no timeout argument and have hung for 20+ minutes
# on a slow endpoint (CI 2026-06-10), so bound every call via the socket default.
AKSHARE_TIMEOUT_SECONDS = 30


@contextmanager
def _socket_timeout(seconds: int):
    """Temporarily bound blocking socket reads so a stalled HTTP call fails fast."""

    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)


def collect_bond_yields(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect real China government bond yield-curve data.

    Tries Tushare yc_cb first; falls back to AkShare bond_china_yield on failure.
    """

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; bond yields must come from a live source.")

    try:
        rows = _collect_tushare(run_date)
    except RuntimeError:
        rows = _collect_akshare(run_date)

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


def _collect_akshare(run_date: str) -> list[dict[str, object]]:
    """Try AkShare sources in order of reliability for the five required tenors.

    1. bond_china_close_return — China Central Depository curve, all five tenors
       present natively, ~2s. Primary fallback.
    2. bond_china_yield — same CCDC data via a different endpoint; 2Y is
       interpolated from 1Y/3Y. Secondary fallback for endpoint outages.

    bond_zh_us_rate (Eastmoney, cross-provider) is intentionally not used: it
    lacks the 1Y tenor, and fabricating it would violate the real-data contract.
    """

    try:
        import akshare  # type: ignore  # noqa: F401
    except Exception as exc:
        raise RuntimeError("AkShare is required as yield curve fallback.") from exc

    for collector in (_collect_akshare_close_return, _collect_akshare_china_yield):
        rows = collector(run_date)
        if rows:
            return rows
    return []


def _collect_akshare_close_return(run_date: str) -> list[dict[str, object]]:
    import akshare as ak  # type: ignore

    target = Date.fromisoformat(run_date)
    for offset in range(0, 10):
        query_date = target - timedelta(days=offset)
        date_str = query_date.strftime("%Y%m%d")
        date_fmt = query_date.strftime("%Y-%m-%d")
        try:
            with _socket_timeout(AKSHARE_TIMEOUT_SECONDS):
                df = ak.bond_china_close_return(
                    symbol="国债", period="1", start_date=date_str, end_date=date_str
                )
        except Exception as exc:
            logger.warning("AkShare bond_china_close_return failed for %s: %s", date_str, exc)
            continue
        if df is None or df.empty:
            continue
        day = df[df["日期"].astype(str) == date_fmt]
        terms = day["期限"].astype(float)
        tenor_map: dict[str, float] = {}
        for term, tenor in REQUIRED_TENORS.items():
            matched = day[(terms - term).abs() < TERM_MATCH_TOLERANCE]
            if not matched.empty:
                tenor_map[tenor] = float(matched.iloc[0]["到期收益率"])
        if set(tenor_map) != set(REQUIRED_TENORS.values()):
            continue
        return [
            {
                "date": run_date,
                "tenor": tenor,
                "yield_value": _validated_yield(tenor, value),
                "data_source": f"akshare_bond_china_close_return:{date_fmt}",
            }
            for tenor, value in tenor_map.items()
        ]
    return []


def _collect_akshare_china_yield(run_date: str) -> list[dict[str, object]]:
    import akshare as ak  # type: ignore

    target = Date.fromisoformat(run_date)
    for offset in range(0, 10):
        query_date = target - timedelta(days=offset)
        date_str = query_date.strftime("%Y%m%d")
        date_fmt = query_date.strftime("%Y-%m-%d")
        try:
            with _socket_timeout(AKSHARE_TIMEOUT_SECONDS):
                df = ak.bond_china_yield(start_date=date_str, end_date=date_str)
        except Exception as exc:
            logger.warning("AkShare bond_china_yield failed for %s: %s", date_str, exc)
            continue
        if df is None or df.empty:
            continue
        cgb = df[df["曲线名称"] == "中债国债收益率曲线"]
        if cgb.empty:
            continue
        row = cgb.iloc[0]
        # AkShare has no 2Y tenor; interpolate linearly from 1Y and 3Y.
        y1 = float(row["1年"])
        y3 = float(row["3年"])
        tenor_map = {
            "1Y": y1,
            "2Y": (y1 + y3) / 2,
            "5Y": float(row["5年"]),
            "10Y": float(row["10年"]),
            "30Y": float(row["30年"]),
        }
        return [
            {
                "date": run_date,
                "tenor": tenor,
                "yield_value": _validated_yield(tenor, value),
                "data_source": f"akshare_bond_china_yield:{date_fmt}",
            }
            for tenor, value in tenor_map.items()
        ]
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

"""Independent ChinaBond versus CFETS government-yield curve check."""

from __future__ import annotations

import logging
from datetime import date as Date
from datetime import timedelta

from bond_futures_monitor.collectors.status import CollectionResult


logger = logging.getLogger(__name__)
TENORS = {1.0: "1Y", 3.0: "3Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}


def collect_yield_curve_comparison(run_date: str) -> list[dict[str, object]]:
    """Collect the latest common official observation from both curve publishers."""

    try:
        return _collect_yield_curve_comparison(run_date)
    except Exception:
        logger.warning("ChinaBond-CFETS curve comparison is unavailable for %s.", run_date, exc_info=True)
        return []


def collect_yield_curve_comparison_result(run_date: str) -> CollectionResult[dict[str, object]]:
    try:
        rows = _collect_yield_curve_comparison(run_date)
    except Exception as exc:
        logger.warning("ChinaBond-CFETS curve comparison is unavailable for %s.", run_date, exc_info=True)
        return CollectionResult([], "unavailable", "chinabond+cfets", str(exc))
    observation = str(rows[0]["observation_date"]) if rows else None
    message = "中债与 CFETS 共同日曲线齐全" if rows else "10 日回溯窗口内无完整共同观测"
    return CollectionResult(rows, "ok" if rows else "unavailable", "chinabond+cfets", message, observation)


def _collect_yield_curve_comparison(run_date: str) -> list[dict[str, object]]:
    import akshare as ak  # type: ignore

    target = Date.fromisoformat(run_date)
    for offset in range(10):
        observation = target - timedelta(days=offset)
        compact = observation.strftime("%Y%m%d")
        iso = observation.isoformat()
        try:
            cfets = ak.bond_china_close_return(symbol="国债", period="1", start_date=compact, end_date=compact)
            chinabond = ak.bond_china_yield(start_date=compact, end_date=compact)
        except Exception as exc:
            logger.info("Curve comparison has no usable observation for %s: %s", iso, exc)
            continue
        if cfets is None or cfets.empty or chinabond is None or chinabond.empty:
            continue
        cfets_day = cfets[cfets["日期"].astype(str) == iso]
        chinabond_day = chinabond[
            (chinabond["曲线名称"] == "中债国债收益率曲线") & (chinabond["日期"].astype(str) == iso)
        ]
        if cfets_day.empty or chinabond_day.empty:
            continue
        cb_row = chinabond_day.iloc[0]
        rows: list[dict[str, object]] = []
        for years, tenor in TENORS.items():
            matched = cfets_day[(cfets_day["期限"].astype(float) - years).abs() < 0.01]
            if matched.empty:
                break
            cfets_value = float(matched.iloc[0]["到期收益率"])
            chinabond_value = float(cb_row[f"{int(years)}年"])
            rows.append(
                {
                    "date": run_date,
                    "observation_date": iso,
                    "tenor": tenor,
                    "chinabond_yield": chinabond_value,
                    "cfets_yield": cfets_value,
                    "deviation_bp": (cfets_value - chinabond_value) * 100,
                    "chinabond_source": f"akshare_chinabond_curve:{iso}",
                    "cfets_source": f"akshare_chinamoney_cfets_curve:{iso}",
                }
            )
        if len(rows) == len(TENORS):
            return rows
    return []

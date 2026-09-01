"""Money-market funding-rate collector."""

from __future__ import annotations

import logging
import os
from datetime import date as Date

from bond_futures_monitor.retry import retry_call


REQUIRED_RATE_NAMES = {"DR001", "DR007", "R007", "SHIBOR_ON", "SHIBOR_7D"}

logger = logging.getLogger(__name__)

# Plausible annualized money-market rate range (percent). Values outside this
# range indicate a wrong source field or corrupted data, not a real market move.
MIN_PLAUSIBLE_RATE = 0.0
MAX_PLAUSIBLE_RATE = 20.0


def collect_funding_rates(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect real interbank funding rates, preferring open AkShare sources."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; funding rates must come from a live source.")

    try:
        rows = _collect_akshare(run_date)
    except RuntimeError:
        logger.warning("AkShare funding-rate query failed for %s.", run_date, exc_info=True)
        rows = []
    missing = REQUIRED_RATE_NAMES - {str(row["rate_name"]) for row in rows}
    if missing:
        try:
            fallback = _collect_tushare(run_date)
        except RuntimeError:
            logger.warning("Tushare funding fallback is unavailable for %s.", run_date, exc_info=True)
        else:
            existing = {str(row["rate_name"]) for row in rows}
            rows.extend(row for row in fallback if str(row["rate_name"]) not in existing)
    available = {row["rate_name"] for row in rows}
    if not REQUIRED_RATE_NAMES.issubset(available):
        raise RuntimeError(
            "Live funding-rate coverage is incomplete: "
            f"expected at least {sorted(REQUIRED_RATE_NAMES)}, got {sorted(available) or 'none'} for {run_date}."
        )
    return rows


def _collect_akshare(run_date: str) -> list[dict[str, object]]:
    """Collect CFETS repo fixings and Shibor without requiring Tushare permissions."""

    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise RuntimeError("AkShare is required for funding-rate fallback.") from exc

    trade_date = Date.fromisoformat(run_date).strftime("%Y%m%d")
    try:
        repo = retry_call(
            lambda: ak.repo_rate_hist(start_date=trade_date, end_date=trade_date),
            description=f"AkShare CFETS repo fixings for {trade_date}",
        )
        shibor = retry_call(
            ak.macro_china_shibor_all,
            description=f"AkShare Shibor history for {trade_date}",
        )
    except Exception as exc:
        raise RuntimeError(f"AkShare funding-rate query failed for {trade_date}.") from exc

    rows = _rows_from_akshare_repo(repo, run_date)
    rows.extend(_rows_from_akshare_shibor(shibor, run_date))
    return rows


def _rows_from_akshare_repo(df, run_date: str) -> list[dict[str, object]]:
    if df is None or df.empty or "date" not in df.columns:
        return []
    matched = df[df["date"].astype(str) == run_date]
    if matched.empty:
        return []
    first = matched.iloc[-1]
    return [
        {
            "date": run_date,
            "rate_name": rate_name,
            "rate_value": _validated_rate(rate_name, first[field]),
            "data_source": f"akshare_chinamoney_repo_rate:{run_date}",
        }
        for rate_name, field in (("DR001", "FDR001"), ("DR007", "FDR007"), ("R007", "FR007"))
    ]


def _rows_from_akshare_shibor(df, run_date: str) -> list[dict[str, object]]:
    if df is None or df.empty or "日期" not in df.columns:
        return []
    matched = df[df["日期"].astype(str) == run_date]
    if matched.empty:
        return []
    first = matched.iloc[-1]
    return [
        {
            "date": run_date,
            "rate_name": rate_name,
            "rate_value": _validated_rate(rate_name, first[field]),
            "data_source": f"akshare_jin10_shibor:{run_date}",
        }
        for rate_name, field in (("SHIBOR_ON", "O/N-定价"), ("SHIBOR_7D", "1W-定价"))
    ]


def _collect_tushare(run_date: str) -> list[dict[str, object]]:
    try:
        import tushare as ts  # type: ignore
    except Exception as exc:
        raise RuntimeError("Tushare is required for funding rates.") from exc

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for funding rates.")

    trade_date = Date.fromisoformat(run_date).strftime("%Y%m%d")
    pro = ts.pro_api(token)
    rows: list[dict[str, object]] = []

    try:
        shibor = retry_call(lambda: pro.shibor(date=trade_date), description=f"Tushare shibor for {trade_date}")
    except Exception as exc:
        raise RuntimeError(f"Tushare shibor failed for {trade_date}.") from exc
    if shibor is not None and not shibor.empty:
        first = shibor.iloc[0]
        rows.extend(
            [
                {
                    "date": run_date,
                    "rate_name": "SHIBOR_ON",
                    "rate_value": _validated_rate("SHIBOR_ON", first["on"]),
                    "data_source": f"tushare_shibor:{trade_date}",
                },
                {
                    "date": run_date,
                    "rate_name": "SHIBOR_7D",
                    "rate_value": _validated_rate("SHIBOR_7D", first["1w"]),
                    "data_source": f"tushare_shibor:{trade_date}",
                },
            ]
        )

    try:
        repo = retry_call(
            lambda: pro.repo_daily(trade_date=trade_date),
            description=f"Tushare repo_daily for {trade_date}",
        )
    except Exception as exc:
        raise RuntimeError(f"Tushare repo_daily failed for {trade_date}.") from exc
    if repo is not None and not repo.empty:
        repo_code_map = [
            ("DR001.IB", "DR001"),
            ("DR007.IB", "DR007"),
            ("R007.IB", "R007"),
            ("206007.SH", "R007"),
        ]
        seen = {str(row["rate_name"]) for row in rows}
        for code, name in repo_code_map:
            if name in seen:
                continue
            matched = repo[repo["ts_code"].astype(str) == code]
            if matched.empty:
                continue
            rows.append(
                {
                    "date": run_date,
                    "rate_name": name,
                    # Tushare repo_daily has no "rate" column; for repos the
                    # volume-weighted average price ("weight") IS the rate, which
                    # matches the official DR007/R007 fixing definition.
                    "rate_value": _validated_rate(name, matched.iloc[0]["weight"]),
                    "data_source": f"tushare_repo_daily:{trade_date}",
                }
            )
            seen.add(name)
    return rows


def _validated_rate(rate_name: str, value: object) -> float:
    """Convert a rate value and fail loudly when it is missing or implausible."""

    try:
        rate = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Funding rate {rate_name} is not numeric: {value!r}.") from exc
    # NaN fails both comparisons, so it is rejected here as well.
    if not MIN_PLAUSIBLE_RATE < rate < MAX_PLAUSIBLE_RATE:
        raise RuntimeError(
            f"Funding rate {rate_name}={rate} is outside the plausible range "
            f"({MIN_PLAUSIBLE_RATE}, {MAX_PLAUSIBLE_RATE}); the source field may be wrong."
        )
    return rate

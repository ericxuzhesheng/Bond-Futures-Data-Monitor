"""Macro fundamental-indicator collector (LPR, CPI, PPI, PMI)."""

from __future__ import annotations

import os
from datetime import date as Date

from bond_futures_monitor.retry import retry_call


REQUIRED_INDICATORS = {"LPR_1Y", "LPR_5Y", "CPI_YOY", "PPI_YOY", "PMI_MFG"}

# Macro releases are monthly (CPI/PPI/PMI) or change rarely (LPR), so the
# collector records the latest published value as of the run date and keeps
# the underlying release period in a separate column.
MONTHLY_LOOKBACK_MONTHS = 4

# Plausible ranges (percent for rates and YoY prints, index points for PMI).
# Values outside these ranges indicate a wrong source field, not a real print.
PLAUSIBLE_RANGES = {
    "LPR_1Y": (0.0, 20.0),
    "LPR_5Y": (0.0, 20.0),
    "CPI_YOY": (-10.0, 25.0),
    "PPI_YOY": (-25.0, 30.0),
    "PMI_MFG": (20.0, 80.0),
}


def collect_macro_indicators(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect the latest real macro fundamentals from Tushare as of run_date."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; macro indicators must come from a live source.")

    rows = _collect_tushare(run_date)
    available = {row["indicator"] for row in rows}
    if not REQUIRED_INDICATORS.issubset(available):
        raise RuntimeError(
            "Live macro-indicator coverage is incomplete: "
            f"expected at least {sorted(REQUIRED_INDICATORS)}, got {sorted(available) or 'none'} for {run_date}."
        )
    return rows


def _collect_tushare(run_date: str) -> list[dict[str, object]]:
    try:
        import tushare as ts  # type: ignore
    except Exception as exc:
        raise RuntimeError("Tushare is required for macro indicators.") from exc

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for macro indicators.")

    pro = ts.pro_api(token)
    end_date = Date.fromisoformat(run_date)
    rows = _lpr_rows(pro, run_date, end_date)
    rows.extend(_monthly_rows(pro, run_date, end_date))
    return rows


def _lpr_rows(pro, run_date: str, end_date: Date) -> list[dict[str, object]]:
    end = end_date.strftime("%Y%m%d")
    # LPR can stay unchanged for many months and the source's release history
    # may lag, so fetch the full series and take the latest print <= run_date
    # instead of using a fixed lookback window.
    try:
        df = retry_call(lambda: pro.shibor_lpr(), description="Tushare shibor_lpr history")
    except Exception as exc:
        raise RuntimeError("Tushare shibor_lpr failed.") from exc
    if df is not None and not df.empty:
        df = df[df["date"].astype(str) <= end]
    if df is None or df.empty:
        raise RuntimeError(f"Tushare shibor_lpr has no rows on or before {end}.")

    latest = df.sort_values("date").iloc[-1]
    period = str(latest["date"])
    period_iso = f"{period[:4]}-{period[4:6]}-{period[6:8]}"
    return [
        {
            "date": run_date,
            "indicator": indicator,
            "value": _validated_value(indicator, latest[field]),
            "period": period_iso,
            "data_source": f"tushare_shibor_lpr:{period}",
        }
        for indicator, field in (("LPR_1Y", "1y"), ("LPR_5Y", "5y"))
    ]


def _monthly_rows(pro, run_date: str, end_date: Date) -> list[dict[str, object]]:
    start_m = _month_offset(end_date, -MONTHLY_LOOKBACK_MONTHS)
    end_m = end_date.strftime("%Y%m")
    specs = (
        ("CPI_YOY", "cn_cpi", ("nt_yoy",)),
        ("PPI_YOY", "cn_ppi", ("ppi_yoy",)),
        # Tushare renamed the manufacturing-PMI column across interface
        # versions, so probe the known candidates in order.
        ("PMI_MFG", "cn_pmi", ("pmi010000", "pmi", "man_pmi")),
    )
    rows: list[dict[str, object]] = []
    for indicator, api_name, fields in specs:
        api = getattr(pro, api_name)
        try:
            df = retry_call(
                lambda api=api: api(start_m=start_m, end_m=end_m),
                description=f"Tushare {api_name} for {start_m}-{end_m}",
            )
        except Exception as exc:
            raise RuntimeError(f"Tushare {api_name} failed for {start_m}-{end_m}.") from exc
        value, period = latest_monthly_value(df, fields, description=api_name)
        rows.append(
            {
                "date": run_date,
                "indicator": indicator,
                "value": _validated_value(indicator, value),
                "period": f"{period[:4]}-{period[4:]}",
                "data_source": f"tushare_{api_name}:{period}",
            }
        )
    return rows


def latest_monthly_value(df, fields: tuple[str, ...], description: str = "monthly macro") -> tuple[object, str]:
    """Return (value, YYYYMM period) for the latest month with a usable field."""

    if df is None or df.empty:
        raise RuntimeError(f"Tushare {description} returned no rows.")
    # Tushare interfaces are inconsistent about column casing (cn_pmi returns
    # MONTH/PMI010000 uppercase), so match column names case-insensitively.
    columns_by_lower = {str(column).lower(): column for column in df.columns}
    month_column = columns_by_lower.get("month")
    if month_column is None:
        raise RuntimeError(f"Tushare {description} has no month column; got {list(df.columns)}.")
    available_fields = [columns_by_lower[field.lower()] for field in fields if field.lower() in columns_by_lower]
    if not available_fields:
        raise RuntimeError(
            f"Tushare {description} has none of the expected fields {list(fields)}; got {list(df.columns)}."
        )
    ordered = df.sort_values(month_column, ascending=False)
    for _, row in ordered.iterrows():
        for field in available_fields:
            value = row[field]
            if not _is_missing(value):
                return value, str(row[month_column])[:6]
    raise RuntimeError(f"Tushare {description} has no non-null value in fields {available_fields}.")


def _month_offset(day: Date, months: int) -> str:
    total = day.year * 12 + (day.month - 1) + months
    return f"{total // 12:04d}{total % 12 + 1:02d}"


def _is_missing(value: object) -> bool:
    if value is None or value == "":
        return True
    return isinstance(value, float) and value != value  # NaN


def _validated_value(indicator: str, value: object) -> float:
    """Convert a macro value and fail loudly when it is missing or implausible."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Macro indicator {indicator} is not numeric: {value!r}.") from exc
    low, high = PLAUSIBLE_RANGES[indicator]
    # NaN fails both comparisons, so it is rejected here as well.
    if not low < number < high:
        raise RuntimeError(
            f"Macro indicator {indicator}={number} is outside the plausible range "
            f"({low}, {high}); the source field may be wrong."
        )
    return number

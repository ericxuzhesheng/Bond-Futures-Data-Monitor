"""Trading-day gate for scheduled daily reports; unknown dates must fail closed."""

from __future__ import annotations

import logging
import os
from datetime import date

import pandas as pd

from bond_futures_monitor.retry import retry_call


logger = logging.getLogger(__name__)


def is_trading_day(run_date: str) -> bool:
    """Use the CFFEX calendar, with the public mainland calendar as a fallback."""
    target = date.fromisoformat(run_date)
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if token:
        try:
            import tushare as ts

            compact = target.strftime("%Y%m%d")
            pro = ts.pro_api(token)
            calendar = retry_call(
                lambda: pro.fut_trade_cal(
                    exchange="CFFEX", start_date=compact, end_date=compact,
                ),
                description="CFFEX trading calendar",
            )
            matched = calendar[
                (calendar["cal_date"].astype(str) == compact)
                & (calendar["exchange"] == "CFFEX")
            ]
            if len(matched) != 1 or str(matched.iloc[0]["is_open"]) not in {"0", "1"}:
                raise ValueError("CFFEX calendar did not return one explicit open/closed state")
            return str(matched.iloc[0]["is_open"]) == "1"
        except Exception as exc:
            logger.warning("CFFEX calendar unavailable (%s); trying public calendar.", type(exc).__name__)

    try:
        import akshare as ak

        calendar = retry_call(ak.tool_trade_date_hist_sina, description="Public trading calendar")
        dates = pd.to_datetime(calendar["trade_date"], errors="raise").dt.date
        if dates.empty or dates.isna().any() or not dates.min() <= target <= dates.max():
            raise ValueError("Requested date is outside the verified calendar coverage")
        return target in set(dates)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot verify trading calendar for {run_date}; refusing to treat missing data as a holiday."
        ) from exc

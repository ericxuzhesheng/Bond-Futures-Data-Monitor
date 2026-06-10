"""Shared Tushare CLS news feed fetcher with per-date caching.

Both the policy-news and open-market-operation collectors consume the same
``pro.news(src="cls", ...)`` feed for one run date. Caching here ensures the
Tushare API is hit only once per date per process.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from bond_futures_monitor.retry import retry_call


logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def fetch_cls_news(run_date: str) -> tuple[dict[str, str], ...]:
    """Fetch one day's CLS news items as (title, content, url) dicts."""

    try:
        import tushare as ts  # type: ignore
    except Exception as exc:
        raise RuntimeError("Tushare is required for policy/news text.") from exc

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for policy/news text.")

    pro = ts.pro_api(token)
    try:
        df = retry_call(
            lambda: pro.news(src="cls", start_date=f"{run_date} 00:00:00", end_date=f"{run_date} 23:59:59"),
            description=f"Tushare news query for {run_date}",
        )
    except Exception as exc:
        raise RuntimeError(f"Tushare news query failed for {run_date}.") from exc

    if df is None or df.empty:
        logger.warning("Tushare news feed returned no rows for %s.", run_date)
        return ()

    items: list[dict[str, str]] = []
    for _, item in df.iterrows():
        items.append(
            {
                "title": str(item.get("title") or "").strip(),
                "content": str(item.get("content") or "").strip(),
                "url": str(item.get("url") or ""),
            }
        )
    return tuple(items)

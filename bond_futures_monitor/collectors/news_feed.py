"""Shared CLS news feed fetcher with per-date caching.

Both the policy-news and open-market-operation collectors consume the same
AkShare's public CLS feed is preferred. Tushare remains a fallback when its
news permission is available. Caching ensures the upstream feed is hit only
once per date per process.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from bond_futures_monitor.retry import retry_call


logger = logging.getLogger(__name__)
_FETCH_STATUS: dict[str, tuple[str, str]] = {}


@lru_cache(maxsize=8)
def fetch_cls_news(run_date: str) -> tuple[dict[str, str], ...]:
    """Fetch one day's CLS news items as (title, content, url) dicts."""

    items = _fetch_akshare_cls_news(run_date)
    if items:
        _FETCH_STATUS[run_date] = ("ok", "AkShare 财联社电报可用")
        return items

    try:
        return _fetch_tushare_cls_news(run_date)
    except RuntimeError:
        _FETCH_STATUS[run_date] = ("unavailable", "AkShare 无目标日历史电报，且 Tushare news 无权限")
        logger.warning(
            "No accessible CLS news source for %s; continuing without text signals.",
            run_date,
            exc_info=True,
        )
        return ()


def get_cls_news_status(run_date: str) -> tuple[str, str]:
    """Return the status recorded by the cached fetch for report provenance."""

    return _FETCH_STATUS.get(run_date, ("empty", "当日未匹配到利率债关键词"))


def _fetch_akshare_cls_news(run_date: str) -> tuple[dict[str, str], ...]:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return ()

    try:
        df = retry_call(
            lambda: ak.stock_info_global_cls(symbol="全部"),
            description=f"AkShare CLS news query for {run_date}",
        )
    except Exception:
        logger.warning("AkShare CLS news query failed for %s.", run_date, exc_info=True)
        return ()
    if df is None or df.empty or "发布日期" not in df.columns:
        return ()

    matched = df[df["发布日期"].astype(str) == run_date]
    return tuple(
        {
            "title": str(item.get("标题") or "").strip(),
            "content": str(item.get("内容") or "").strip(),
            "url": "",
            "data_source": f"akshare_cls_telegraph:{run_date}",
        }
        for _, item in matched.iterrows()
    )


def _fetch_tushare_cls_news(run_date: str) -> tuple[dict[str, str], ...]:

    try:
        import tushare as ts  # type: ignore
    except Exception as exc:
        raise RuntimeError("Tushare is required for policy/news fallback.") from exc

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
                "data_source": f"tushare_news_cls:{run_date}",
            }
        )
    return tuple(items)

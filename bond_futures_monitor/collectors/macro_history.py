"""Official NBS history for the macro trend panel."""

from __future__ import annotations

import logging
import re
from datetime import date as Date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from bond_futures_monitor.collectors.status import CollectionResult


logger = logging.getLogger(__name__)
NBS_LIST_URL = "https://www.stats.gov.cn/sj/zxfb/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BondFuturesDataMonitor/1.0)"}


def collect_nbs_macro_history(run_date: str, periods: int = 6) -> list[dict[str, object]]:
    """Collect the last *periods* CPI, PPI and manufacturing-PMI releases."""

    try:
        return _collect_nbs_macro_history(run_date, periods)
    except Exception:
        logger.warning("Official NBS macro history is unavailable for %s.", run_date, exc_info=True)
        return []


def collect_nbs_macro_history_result(run_date: str, periods: int = 6) -> CollectionResult[dict[str, object]]:
    try:
        rows = _collect_nbs_macro_history(run_date, periods)
    except Exception as exc:
        logger.warning("Official NBS macro history is unavailable for %s.", run_date, exc_info=True)
        return CollectionResult([], "unavailable", "nbs_official_release", str(exc))
    expected = periods * len(_indicators())
    status = "ok" if len(rows) >= expected else "partial" if rows else "empty"
    message = f"获取 {len(rows)}/{expected} 条官方宏观历史"
    observation = max((str(row["release_date"]) for row in rows), default=None)
    return CollectionResult(rows, status, "nbs_official_release", message, observation)


def _collect_nbs_macro_history(run_date: str, periods: int) -> list[dict[str, object]]:
    target = Date.fromisoformat(run_date)
    session = requests.Session()
    links: dict[str, tuple[str, str]] = {}
    for page in range(8):
        url = NBS_LIST_URL if page == 0 else urljoin(NBS_LIST_URL, f"index_{page}.html")
        response = session.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            title = " ".join(anchor.get_text(" ", strip=True).split())
            indicator = _indicator_from_title(title)
            if indicator:
                article_url = urljoin(url, anchor["href"])
                release_date = _date_from_url(article_url)
                if release_date and Date.fromisoformat(release_date) <= target:
                    links[article_url] = (title, indicator)
        counts = {key: sum(1 for _, indicator in links.values() if indicator == key) for key in _indicators()}
        if all(count >= periods for count in counts.values()):
            break

    rows: list[dict[str, object]] = []
    for article_url, (title, indicator) in links.items():
        period = _period_from_title(title)
        value = _value_from_title(title, indicator)
        if indicator == "PMI_MFG" or value is None:
            try:
                response = session.get(article_url, headers=HEADERS, timeout=20)
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("NBS release is temporarily unavailable: %s (%s)", article_url, exc)
                continue
            response.encoding = "utf-8"
            text = " ".join(BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True).split())
            value = _value_from_text(text, indicator)
        if period and value is not None:
            rows.append(
                {
                    "date": run_date,
                    "indicator": indicator,
                    "period": period,
                    "value": value,
                    "release_date": _date_from_url(article_url),
                    "source_url": article_url,
                    "data_source": "nbs_official_release",
                }
            )

    selected: list[dict[str, object]] = []
    for indicator in _indicators():
        candidates = sorted(
            (row for row in rows if row["indicator"] == indicator),
            key=lambda row: str(row["period"]),
            reverse=True,
        )
        selected.extend(candidates[:periods])
    return selected


def _indicators() -> tuple[str, ...]:
    return "CPI_YOY", "PPI_YOY", "PMI_MFG"


def _indicator_from_title(title: str) -> str | None:
    if "居民消费价格" in title and "同比" in title:
        return "CPI_YOY"
    if "工业生产者出厂价格" in title and "同比" in title:
        return "PPI_YOY"
    if "采购经理指数运行情况" in title:
        return "PMI_MFG"
    return None


def _date_from_url(url: str) -> str | None:
    match = re.search(r"t(\d{8})_", url)
    if not match:
        return None
    value = match.group(1)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _period_from_title(title: str) -> str | None:
    match = re.search(r"(\d{4})年(\d{1,2})月", title)
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}" if match else None


def _value_from_title(title: str, indicator: str) -> float | None:
    if indicator == "PMI_MFG":
        return None
    return _signed_percent(title)


def _value_from_text(text: str, indicator: str) -> float | None:
    if indicator == "PMI_MFG":
        patterns = (
            r"制造业采购经理指数\s*[（(]\s*PMI\s*[）)]\s*为\s*([0-9]+(?:\.[0-9]+)?)\s*%",
            r"制造业\s*PMI\s*为\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None
    return _signed_percent(text)


def _signed_percent(text: str) -> float | None:
    transition = re.search(
        r"同比由上月(?:上涨|下降)\s*[0-9]+(?:\.[0-9]+)?\s*%\s*转为(上涨|下降)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*%",
        text,
    )
    if transition:
        value = float(transition.group(2))
        return -value if transition.group(1) == "下降" else value
    match = re.search(r"同比\s*(上涨|下降|持平)\s*([0-9]+(?:\.[0-9]+)?)?%?", text)
    if not match:
        return None
    if match.group(1) == "持平":
        return 0.0
    if not match.group(2):
        return None
    value = float(match.group(2))
    return -value if match.group(1) == "下降" else value

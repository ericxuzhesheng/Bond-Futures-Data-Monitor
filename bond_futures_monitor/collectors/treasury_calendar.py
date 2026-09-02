"""Treasury issuance calendar parsed from official MOF notices."""

from __future__ import annotations

import logging
import re
from datetime import date as Date
from datetime import timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from bond_futures_monitor.collectors.status import CollectionResult


logger = logging.getLogger(__name__)
MOF_LIST_URL = "https://www.mof.gov.cn/gkml/bulinggonggao/tongzhitonggao/index.htm"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BondFuturesDataMonitor/1.0)"}


def collect_treasury_issuance_calendar(run_date: str) -> list[dict[str, object]]:
    """Return recently completed and announced upcoming Treasury auctions."""

    try:
        return _collect_treasury_issuance_calendar(run_date)
    except Exception:
        logger.warning("Official MOF Treasury calendar is unavailable for %s.", run_date, exc_info=True)
        return []


def collect_treasury_issuance_calendar_result(run_date: str) -> CollectionResult[dict[str, object]]:
    try:
        rows = _collect_treasury_issuance_calendar(run_date)
    except Exception as exc:
        logger.warning("Official MOF Treasury calendar is unavailable for %s.", run_date, exc_info=True)
        return CollectionResult([], "unavailable", "mof_official_notice", str(exc))
    message = "已取得财政部公告" if rows else "查询窗口内未发现已公告招标安排"
    return CollectionResult(rows, "ok" if rows else "empty", "mof_official_notice", message)


def _collect_treasury_issuance_calendar(run_date: str) -> list[dict[str, object]]:
    target = Date.fromisoformat(run_date)
    session = requests.Session()
    candidates: dict[str, str] = {}
    base = MOF_LIST_URL.rsplit("/", 1)[0] + "/"
    for page in range(4):
        url = MOF_LIST_URL if page == 0 else urljoin(base, f"index_{page}.htm")
        response = session.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            title = " ".join(anchor.get_text(" ", strip=True).split())
            if "国债" not in title or "发行工作有关事宜" not in title:
                continue
            article_url = urljoin(url, anchor["href"])
            release_date = _date_from_url(article_url)
            if release_date and target - timedelta(days=25) <= Date.fromisoformat(release_date) <= target:
                candidates[article_url] = title

    rows: list[dict[str, object]] = []
    successful_article_fetches = 0
    for article_url, title in candidates.items():
        try:
            response = session.get(article_url, headers=HEADERS, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("MOF notice is temporarily unavailable: %s (%s)", article_url, exc)
            continue
        successful_article_fetches += 1
        response.encoding = "utf-8"
        text = " ".join(BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True).split())
        parsed = parse_treasury_notice(text)
        if not parsed:
            continue
        auction = Date.fromisoformat(str(parsed["auction_date"]))
        if target - timedelta(days=3) <= auction <= target + timedelta(days=14):
            rows.append(
                {
                    "date": run_date,
                    "auction_date": parsed["auction_date"],
                    "title": title,
                    "tenor": parsed["tenor"],
                    "planned_amount": parsed["planned_amount"],
                    "source_url": article_url,
                    "data_source": "mof_official_notice",
                }
            )
    if candidates and successful_article_fetches == 0:
        raise RuntimeError(f"MOF list returned {len(candidates)} notices but every article request failed")
    return sorted(rows, key=lambda row: (str(row["auction_date"]), str(row["title"])))


def parse_treasury_notice(text: str) -> dict[str, object] | None:
    """Extract auction date, tenor and planned amount from one MOF notice."""

    date_match = re.search(r"招标时间。\s*(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    tenor_match = re.search(r"为\s*(\d+)年期[^。]*债", text)
    tenor_days_match = re.search(r"为期限\s*(\d+)天的贴现债", text)
    amount_match = re.search(r"(?:竞争性招标)?面值总额\s*([0-9.]+)亿元", text)
    if not date_match or not amount_match or (not tenor_match and not tenor_days_match):
        return None
    tenor = f"{tenor_match.group(1)}Y" if tenor_match else f"{tenor_days_match.group(1)}D"
    return {
        "auction_date": f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}",
        "tenor": tenor,
        "planned_amount": float(amount_match.group(1)),
    }


def _date_from_url(url: str) -> str | None:
    match = re.search(r"t(\d{8})_", url)
    if not match:
        return None
    value = match.group(1)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"

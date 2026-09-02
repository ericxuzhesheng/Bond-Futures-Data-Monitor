"""Open-market-operation collector."""

from __future__ import annotations

import logging
import re
from datetime import date as Date, timedelta
from urllib.parse import urljoin

from bond_futures_monitor.collectors.news_feed import fetch_cls_news
from bond_futures_monitor.retry import retry_call


logger = logging.getLogger(__name__)

OMO_KEYWORDS = ("央行", "人民银行", "公开市场", "逆回购", "净投放", "净回笼", "到期")
PBC_OMO_LIST_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/125475/index.html"
PBC_OMO_HISTORY_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/125475/17081-{page}.html"


def collect_open_market_operations(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect PBC operations, deriving maturities from earlier official notices.

    The PBC notice chain is preferred. CLS text remains a fallback when an older
    official notice cannot be located, because net injection must not be inferred
    without a known maturity amount.
    """

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; open-market operations must come from a live source.")

    try:
        official_rows = _collect_pbc_official(run_date)
    except RuntimeError:
        logger.warning("PBC official OMO query failed for %s.", run_date, exc_info=True)
        official_rows = []
    official_is_complete = bool(official_rows) and all(bool(row.get("_net_complete")) for row in official_rows)
    news_rows = [] if official_is_complete else _collect_tushare_news(run_date)
    rows = _merge_official_and_news_rows(official_rows, news_rows)
    if not rows:
        logger.warning(
            "No complete OMO record found for %s; "
            "scoring the OMO dimension as neutral.",
            run_date,
        )
    return rows


def _collect_pbc_official(run_date: str) -> list[dict[str, object]]:
    """Fetch same-day operation details from the PBC's official notice page."""

    try:
        from bs4 import BeautifulSoup  # type: ignore
        import requests
    except Exception as exc:
        raise RuntimeError("requests and BeautifulSoup are required for PBC OMO notices.") from exc

    def fetch(url: str) -> str:
        response = requests.get(
            url,
            headers={"User-Agent": "Bond-Futures-Data-Monitor/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    try:
        listing_htmls = [
            retry_call(lambda: fetch(PBC_OMO_LIST_URL), description=f"PBC OMO list for {run_date}")
        ]
        remaining_history_pages = iter((2, 3))
        article_cache: dict[str, str] = {}

        def notice_links(notice_date: str) -> list[tuple[str, str]]:
            links = [link for html in listing_htmls for link in _pbc_notice_links(html, notice_date)]
            while not links:
                try:
                    page = next(remaining_history_pages)
                except StopIteration:
                    break
                listing_htmls.append(
                    retry_call(
                        lambda page=page: fetch(PBC_OMO_HISTORY_URL.format(page=page)),
                        description=f"PBC OMO history page {page} for {run_date}",
                    )
                )
                links = _pbc_notice_links(listing_htmls[-1], notice_date)
            return links

        def notice_rows(notice_date: str) -> tuple[list[dict[str, object]], bool]:
            links = notice_links(notice_date)
            parsed_rows: list[dict[str, object]] = []
            for title, url in links:
                if url not in article_cache:
                    article_html = retry_call(lambda url=url: fetch(url), description=f"PBC OMO notice {url}")
                    article_cache[url] = BeautifulSoup(article_html, "html.parser").get_text(" ", strip=True)
                text = article_cache[url]
                parsed = parse_omo_text(notice_date, title, text, f"pbc_official:{url}")
                if not parsed:
                    parsed = _parse_zero_operation_notice(notice_date, title, text, f"pbc_official:{url}")
                parsed_rows.extend(parsed)
            return parsed_rows, bool(links)

        rows, _ = notice_rows(run_date)
        for row in rows:
            tenor = row.get("tenor_days")
            if not isinstance(tenor, int) or tenor <= 0:
                row["_net_complete"] = False
                continue
            maturity_date = (Date.fromisoformat(run_date) - timedelta(days=tenor)).isoformat()
            maturity_rows, maturity_notice_found = notice_rows(maturity_date)
            maturity = sum(
                float(item["operation_amount"])
                for item in maturity_rows
                if item["operation_type"] == row["operation_type"] and item["tenor_days"] == tenor
            )
            row["maturity_amount"] = maturity
            row["net_injection_amount"] = float(row["operation_amount"]) - maturity
            row["_net_complete"] = maturity_notice_found
        return rows
    except Exception as exc:
        raise RuntimeError(f"PBC official OMO query failed for {run_date}.") from exc


def _pbc_notice_links(html: str, run_date: str) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup  # type: ignore

    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    for anchor in soup.find_all("a"):
        title = anchor.get_text(" ", strip=True)
        if not title.startswith("公开市场业务交易公告 ["):
            continue
        container = anchor.find_parent("td")
        if container is None or run_date not in container.get_text(" ", strip=True):
            continue
        href = str(anchor.get("href") or "")
        if href:
            links.append((title, urljoin(PBC_OMO_LIST_URL, href)))
    return links


def _parse_zero_operation_notice(
    run_date: str,
    title: str,
    text: str,
    data_source: str,
) -> list[dict[str, object]]:
    match = re.search(r"(\d+)\s*天期?逆回购操作量为零", _normalize_text(text))
    if not match:
        return []
    return [{
        "date": run_date,
        "operation_type": "reverse_repo",
        "tenor_days": int(match.group(1)),
        "operation_amount": 0.0,
        "maturity_amount": 0.0,
        "net_injection_amount": 0.0,
        "operation_rate": None,
        "source_title": title[:120],
        "data_source": data_source,
    }]


def _merge_official_and_news_rows(
    official_rows: list[dict[str, object]],
    news_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Prefer complete official rows; use news only when official maturity is unavailable."""

    if not official_rows:
        return news_rows

    merged: list[dict[str, object]] = []
    used_news: set[int] = set()
    for official in official_rows:
        match_index = next(
            (
                index
                for index, news in enumerate(news_rows)
                if index not in used_news
                and news["operation_type"] == official["operation_type"]
                and news["tenor_days"] == official["tenor_days"]
            ),
            None,
        )
        row = {key: value for key, value in official.items() if not key.startswith("_")}
        if bool(official.get("_net_complete")):
            if match_index is not None:
                used_news.add(match_index)
                row["data_source"] = f"{row['data_source']}+{news_rows[match_index]['data_source']}"
            merged.append(row)
        elif match_index is not None:
            news = news_rows[match_index]
            used_news.add(match_index)
            row["maturity_amount"] = news["maturity_amount"]
            row["net_injection_amount"] = float(row["operation_amount"]) - float(news["maturity_amount"])
            row["data_source"] = f"{row['data_source']}+{news['data_source']}"
            merged.append(row)
        else:
            logger.warning(
                "PBC OMO operation found for %s but no maturity total was available; omitting the incomplete net row.",
                official["date"],
            )

    merged.extend(row for index, row in enumerate(news_rows) if index not in used_news)
    return merged


def parse_omo_text(run_date: str, title: str, content: str, data_source: str) -> list[dict[str, object]]:
    """Parse OMO amounts from one real news item."""

    text = _normalize_text(f"{title} {content}")
    if not _is_omo_relevant(text):
        return []
    # Keep current-operation clauses only. News digests can mix a genuine
    # same-day maturity with future plans and unrelated interest-rate stories.
    # A publication date is not an operation date.
    clauses = []
    for clause in re.split(r"[。；;]|(?=\d+、)", text):
        if re.search(r"下周|本周|上周|本月|下月|将(?:在|于|以|开展)|拟开展", clause):
            continue
        if "逆回购" in clause or (clauses and re.search(r"净投放|净回笼|净回收|操作利率|中标利率", clause)):
            clauses.append(clause)
    text = "。".join(clauses)
    if not text:
        return []

    rows: list[dict[str, object]] = []
    operation_amount = _amount_before(text, ("逆回购操作", "买断式逆回购操作", "开展"))
    maturity_amount = _maturity_amount(text)
    net_amount = _net_amount(text)
    tenor_days = _tenor_days(text)
    operation_rate = _operation_rate(text)

    if operation_amount is None and maturity_amount is None and net_amount is None:
        return []

    if operation_amount is None:
        operation_amount = 0.0
    if maturity_amount is None:
        maturity_amount = 0.0
    if net_amount is None:
        net_amount = operation_amount - maturity_amount

    rows.append(
        {
            "date": run_date,
            "operation_type": "outright_reverse_repo" if "买断式逆回购" in text else "reverse_repo",
            "tenor_days": tenor_days,
            "operation_amount": operation_amount,
            "maturity_amount": maturity_amount,
            "net_injection_amount": net_amount,
            "operation_rate": operation_rate,
            "source_title": title[:120] or "公开市场操作",
            "data_source": data_source,
        }
    )
    return rows


def _collect_tushare_news(run_date: str) -> list[dict[str, object]]:
    items = fetch_cls_news(run_date)

    rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, int | None]] = set()
    for item in items:
        parsed_rows = parse_omo_text(run_date, item["title"], item["content"], item["data_source"])
        for row in parsed_rows:
            key = (str(row["operation_type"]), row["tenor_days"] if isinstance(row["tenor_days"], int) else None)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(row)
    return rows


def _is_omo_relevant(text: str) -> bool:
    if "逆回购" not in text:
        return False
    if not any(keyword in text for keyword in OMO_KEYWORDS):
        return False
    noise = ("股份回购", "回购股份", "股票回购", "债券回购业务管理规定")
    return not any(term in text for term in noise)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text.replace(",", "").replace("，", "，"))


def _amount_before(text: str, anchors: tuple[str, ...]) -> float | None:
    for anchor in anchors:
        matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(亿元|万亿元)[^。；;]{0,30}" + re.escape(anchor), text))
        if matches:
            return _amount_to_yi(matches[-1].group(1), matches[-1].group(2))
    matches = list(re.finditer(r"开展[^。；;]{0,30}?(\d+(?:\.\d+)?)\s*(亿元|万亿元)[^。；;]{0,20}?逆回购", text))
    if matches:
        return _amount_to_yi(matches[-1].group(1), matches[-1].group(2))
    return None


def _maturity_amount(text: str) -> float | None:
    patterns = (
        r"有(\d+(?:\.\d+)?)\s*(亿元|万亿元)[^。；;]{0,20}?逆回购到期",
        r"逆回购到期[^。；;]{0,20}?(\d+(?:\.\d+)?)\s*(亿元|万亿元)",
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, text))
        if matches:
            return _amount_to_yi(matches[-1].group(1), matches[-1].group(2))
    return None


def _net_amount(text: str) -> float | None:
    patterns = (
        (r"净投放(\d+(?:\.\d+)?)\s*(亿元|万亿元)", 1.0),
        (r"净回笼(\d+(?:\.\d+)?)\s*(亿元|万亿元)", -1.0),
        (r"净回收(\d+(?:\.\d+)?)\s*(亿元|万亿元)", -1.0),
    )
    for pattern, sign in patterns:
        matches = list(re.finditer(pattern, text))
        if matches:
            return sign * _amount_to_yi(matches[-1].group(1), matches[-1].group(2))
    return None


def _tenor_days(text: str) -> int | None:
    match = re.search(r"(\d+)\s*天期?逆回购", text)
    if match:
        return int(match.group(1))
    match = re.search(r"期限为?(\d+)\s*个月", text)
    if match:
        return int(match.group(1)) * 30
    return None


def _operation_rate(text: str) -> float | None:
    patterns = (
        r"(?:操作利率|中标利率|逆回购利率)[^。；;]{0,10}?(\d+(?:\.\d+)?)%",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = float(match.group(1))
            return value if 0 <= value <= 20 else None
    return None


def _amount_to_yi(value: str, unit: str) -> float:
    amount = float(value)
    if unit == "万亿元":
        return amount * 10000
    return amount

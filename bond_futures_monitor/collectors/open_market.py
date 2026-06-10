"""Open-market-operation collector."""

from __future__ import annotations

import re

from bond_futures_monitor.collectors.news_feed import fetch_cls_news


OMO_KEYWORDS = ("央行", "人民银行", "公开市场", "逆回购", "净投放", "净回笼", "到期")


def collect_open_market_operations(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect and parse real PBOC open-market-operation text from Tushare news."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; open-market operations must come from a live source.")

    rows = _collect_tushare_news(run_date)
    if not rows:
        raise RuntimeError(f"No live open-market-operation rows could be parsed for {run_date}.")
    return rows


def parse_omo_text(run_date: str, title: str, content: str, data_source: str) -> list[dict[str, object]]:
    """Parse OMO amounts from one real news item."""

    text = _normalize_text(f"{title} {content}")
    if not _is_omo_relevant(text):
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
        parsed_rows = parse_omo_text(run_date, item["title"], item["content"], f"tushare_news_cls:{run_date}")
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
        r"操作利率[^。；;]{0,10}?(\d+(?:\.\d+)?)%",
        r"利率[^。；;]{0,10}?(\d+(?:\.\d+)?)%",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def _amount_to_yi(value: str, unit: str) -> float:
    amount = float(value)
    if unit == "万亿元":
        return amount * 10000
    return amount

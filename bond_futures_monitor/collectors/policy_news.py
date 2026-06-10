"""Policy and market-news text collector."""

from __future__ import annotations

from bond_futures_monitor.collectors.news_feed import fetch_cls_news


CORE_RATE_TERMS = (
    "央行",
    "人民银行",
    "国债",
    "国债期货",
    "利率债",
    "地方债",
    "专项债",
    "特别国债",
    "超长期特别国债",
    "公开市场",
    "逆回购",
    "MLF",
    "LPR",
    "降准",
    "降息",
    "DR007",
    "SHIBOR",
    "银行间",
    "财政部",
    "国家发改委",
)

MACRO_RATE_TERMS = (
    "货币",
    "流动性",
    "资金",
    "利率",
    "债券",
    "财政",
    "宏观",
    "CPI",
    "PPI",
    "PMI",
    "金融风险",
)

NOISE_TERMS = (
    "ETF",
    "美股",
    "标普500",
    "纳斯达克",
    "道琼斯",
    "加密货币",
    "亚马逊",
    "苹果",
    "英伟达",
    "股票",
    "拟减持",
    "股份",
    "回购股份",
    "增持",
    "持股",
    "资金加仓",
    "员工持股",
    "重大资产重组",
    "全资子公司",
    "债务融资工具",
)

GOVERNMENT_RATE_ANCHORS = (
    "央行",
    "人民银行",
    "国债",
    "国债期货",
    "利率债",
    "地方债",
    "专项债",
    "特别国债",
    "财政部",
    "国家发改委",
    "银行间",
    "DR007",
    "SHIBOR",
    "MLF",
    "LPR",
    "降准",
    "降息",
    "货币政策",
)

HIGH_AUTHORITY_ANCHORS = (
    "央行",
    "人民银行",
    "国债",
    "国债期货",
    "利率债",
    "地方债",
    "专项债",
    "特别国债",
    "财政部",
    "国家发改委",
)


def collect_policy_news(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect real policy/news text from Tushare news feeds."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; policy/news text must come from a live source.")

    rows = _collect_tushare_news(run_date)
    if not rows:
        raise RuntimeError(f"No live policy/news rows matched fixed-income keywords for {run_date}.")
    return rows


def _collect_tushare_news(run_date: str) -> list[dict[str, object]]:
    items = fetch_cls_news(run_date)

    rows: list[dict[str, object]] = []
    seen_titles: set[str] = set()
    for item in items:
        title = item["title"]
        content = item["content"]
        if not title and not content:
            continue
        text = f"{title} {content}"
        if not _is_fixed_income_relevant(text):
            continue
        dedupe_key = title or content[:60]
        if dedupe_key in seen_titles:
            continue
        seen_titles.add(dedupe_key)
        rows.append(
            {
                "date": run_date,
                "title": title or content[:40],
                "source": "财联社",
                "content": content,
                "url": item["url"],
                "data_source": f"tushare_news_cls:{run_date}",
            }
        )
        if len(rows) >= 12:
            break
    return rows


def _is_fixed_income_relevant(text: str) -> bool:
    lowered = text.lower()
    has_core = any(term.lower() in lowered for term in CORE_RATE_TERMS)
    has_macro = any(term.lower() in lowered for term in MACRO_RATE_TERMS)
    has_noise = any(term.lower() in lowered for term in NOISE_TERMS)
    has_anchor = any(term.lower() in lowered for term in GOVERNMENT_RATE_ANCHORS)
    has_high_authority_anchor = any(term.lower() in lowered for term in HIGH_AUTHORITY_ANCHORS)

    if has_noise and not has_high_authority_anchor:
        return False
    if has_core:
        return True
    return has_macro and any(term in text for term in ("人民银行", "财政部", "国家发改委", "银行间", "货币政策"))

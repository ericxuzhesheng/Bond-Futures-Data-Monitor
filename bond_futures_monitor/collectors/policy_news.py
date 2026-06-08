"""Policy and news text collector."""

from __future__ import annotations

import os


def collect_policy_news(run_date: str, use_live_data: bool = False) -> list[dict[str, object]]:
    if use_live_data:
        live_rows = _try_collect_tushare_news(run_date)
        if live_rows:
            return live_rows
    return sample_policy_news(run_date)


def sample_policy_news(run_date: str) -> list[dict[str, object]]:
    return [
        {
            "date": run_date,
            "title": "央行通过公开市场操作投放流动性",
            "source": "样例政策数据",
            "content": (
                "央行开展净投放操作，维护银行体系流动性合理充裕。操作后资金利率有所回落，"
                "短端流动性环境边际改善。"
            ),
            "url": "https://example.com/pboc-liquidity-sample",
            "data_source": "sample_fallback",
        },
        {
            "date": run_date,
            "title": "本月地方政府债供给预计增加",
            "source": "样例宏观数据",
            "content": (
                "市场预计地方政府债发行规模上升，可能增加久期供给压力，并对长端利率债情绪"
                "形成一定扰动。"
            ),
            "url": "https://example.com/bond-supply-sample",
            "data_source": "sample_fallback",
        },
    ]


def _try_collect_tushare_news(run_date: str) -> list[dict[str, object]]:
    try:
        import tushare as ts  # type: ignore
    except Exception:
        return []

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        return []

    pro = ts.pro_api(token)
    keywords = ("央行", "货币", "流动性", "资金", "利率", "债券", "国债", "地方政府债", "金融风险", "宏观")
    try:
        df = pro.news(
            src="cls",
            start_date=f"{run_date} 00:00:00",
            end_date=f"{run_date} 23:59:59",
        )
    except Exception:
        return []

    if df.empty:
        return []

    rows: list[dict[str, object]] = []
    for _, item in df.iterrows():
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        text = f"{title} {content}"
        if not any(keyword in text for keyword in keywords):
            continue
        rows.append(
            {
                "date": run_date,
                "title": title or content[:40],
                "source": "财联社",
                "content": content,
                "url": "",
                "data_source": "tushare_news_cls",
            }
        )
        if len(rows) >= 8:
            break
    return rows

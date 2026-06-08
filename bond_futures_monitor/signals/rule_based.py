"""Transparent rule-based market scoring."""

from __future__ import annotations

from typing import Any


def generate_market_signal(features: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    drivers: list[str] = []
    risks: list[str] = []
    score_items: list[dict[str, Any]] = []

    yield_10y_change = features.get("yield_10y_change")
    if yield_10y_change is not None:
        if yield_10y_change <= -0.01:
            score += _add_score(score_items, "利率方向", 2, "10Y 国债收益率明显下行，对国债期货形成支撑。")
        elif yield_10y_change >= 0.01:
            score += _add_score(score_items, "利率方向", -2, "10Y 国债收益率明显上行，对国债期货形成压力。")

    spread_10y_2y = features.get("spread_10y_2y")
    if spread_10y_2y is not None:
        if spread_10y_2y < 0.35:
            score += _add_score(score_items, "曲线形态", 0.5, "10Y-2Y 利差偏窄，反映市场对中长期利率上行的补偿有限。")
        elif spread_10y_2y > 0.75:
            score += _add_score(score_items, "曲线形态", -0.5, "10Y-2Y 利差偏宽，提示曲线陡峭化和期限溢价压力。")

    dr007_change = features.get("dr007_change")
    if dr007_change is not None:
        if dr007_change <= -0.03:
            score += _add_score(score_items, "资金面", 1, "DR007 下行，显示银行间资金面边际转松。")
        elif dr007_change >= 0.03:
            score += _add_score(score_items, "资金面", -1, "DR007 上行，显示银行间资金面边际收紧。")
    else:
        risks.append("当日缺少 DR007 变化值，资金面判断以可得回购利率和 Shibor 为辅助。")

    avg_futures_return = features.get("avg_futures_return")
    avg_volume_change = features.get("avg_volume_change")
    if avg_futures_return is not None and avg_volume_change is not None:
        if avg_futures_return > 0 and avg_volume_change > 0:
            score += _add_score(score_items, "期货量价", 1, "期货价格上涨且成交活跃度提高，量价配合偏积极。")
        elif avg_futures_return < 0 and avg_volume_change > 0:
            score += _add_score(score_items, "期货量价", -1, "期货价格下跌且成交活跃度提高，量价配合偏消极。")

    ai_score = features.get("avg_ai_sentiment_score")
    if ai_score is not None:
        if ai_score > 0.25:
            score += _add_score(score_items, "文本信号", 1, "政策与新闻文本信号整体偏多。")
        elif ai_score < -0.25:
            score += _add_score(score_items, "文本信号", -1, "政策与新闻文本信号整体偏空。")

    if features.get("spread_30y_10y") is not None and features["spread_30y_10y"] > 0.35:
        risks.append("超长端曲线偏陡可能反映供给压力或期限溢价扰动。")
    details = features.get("details", {})
    sources = details.get("data_sources", {}) if isinstance(details, dict) else {}
    if any("sample_fallback" in values for values in sources.values() if isinstance(values, list)):
        risks.append("部分数据来自样例回退源，需谨慎解读当日结论。")
    risks.append("当实时数据源不可用时，MVP 会使用样例回退数据。")
    risks.append("该信号是规则化研究输出，不是价格预测或交易建议。")

    if score >= 2:
        view = "bullish"
    elif score <= -2:
        view = "bearish"
    else:
        view = "neutral"

    drivers = [item["reason"] for item in score_items if item["score"] != 0]
    if not drivers:
        drivers.append("当日没有单一指标触发强方向阈值。")

    return {
        "date": features["date"],
        "total_score": score,
        "market_view": view,
        "key_drivers": drivers,
        "risk_notes": risks,
        "details": {
            "score_items": score_items,
            "score_summary": _summarize_score_items(score_items),
            "feature_snapshot": features,
        },
    }


def _add_score(score_items: list[dict[str, Any]], category: str, score: float, reason: str) -> float:
    score_items.append({"category": category, "score": score, "reason": reason})
    return score


def _summarize_score_items(score_items: list[dict[str, Any]]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for item in score_items:
        summary[item["category"]] = summary.get(item["category"], 0.0) + float(item["score"])
    return summary

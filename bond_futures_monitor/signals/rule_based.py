"""Transparent rule-based market scoring."""

from __future__ import annotations

from typing import Any


def generate_market_signal(features: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    drivers: list[str] = []
    risks: list[str] = []

    yield_10y_change = features.get("yield_10y_change")
    if yield_10y_change is not None:
        if yield_10y_change <= -0.01:
            score += 2
            drivers.append("10Y 国债收益率明显下行，对国债期货形成支撑。")
        elif yield_10y_change >= 0.01:
            score -= 2
            drivers.append("10Y 国债收益率明显上行，对国债期货形成压力。")

    dr007_change = features.get("dr007_change")
    if dr007_change is not None:
        if dr007_change <= -0.03:
            score += 1
            drivers.append("DR007 下行，显示资金面边际转松。")
        elif dr007_change >= 0.03:
            score -= 1
            drivers.append("DR007 上行，显示资金面边际收紧。")

    avg_futures_return = features.get("avg_futures_return")
    avg_volume_change = features.get("avg_volume_change")
    if avg_futures_return is not None and avg_volume_change is not None:
        if avg_futures_return > 0 and avg_volume_change > 0:
            score += 1
            drivers.append("期货价格上涨且成交活跃度提高，量价配合偏积极。")
        elif avg_futures_return < 0 and avg_volume_change > 0:
            score -= 1
            drivers.append("期货价格下跌且成交活跃度提高，量价配合偏消极。")

    ai_score = features.get("avg_ai_sentiment_score")
    if ai_score is not None:
        if ai_score > 0.25:
            score += 1
            drivers.append("政策与新闻文本信号整体偏多。")
        elif ai_score < -0.25:
            score -= 1
            drivers.append("政策与新闻文本信号整体偏空。")

    if features.get("spread_30y_10y") is not None and features["spread_30y_10y"] > 0.35:
        risks.append("超长端曲线偏陡可能反映供给压力或期限溢价扰动。")
    risks.append("当实时数据源不可用时，MVP 会使用样例回退数据。")
    risks.append("该信号是规则化研究输出，不是价格预测或交易建议。")

    if score >= 2:
        view = "bullish"
    elif score <= -2:
        view = "bearish"
    else:
        view = "neutral"

    if not drivers:
        drivers.append("当日没有单一指标触发强方向阈值。")

    return {
        "date": features["date"],
        "total_score": score,
        "market_view": view,
        "key_drivers": drivers,
        "risk_notes": risks,
        "details": {"feature_snapshot": features},
    }

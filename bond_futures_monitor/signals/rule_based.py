"""Transparent rule-based market scoring."""

from __future__ import annotations

from typing import Any


def generate_market_signal(features: dict[str, Any]) -> dict[str, Any]:
    score_items: list[dict[str, Any]] = []
    risks: list[str] = []

    _score_rates(score_items, features)
    _score_curve(score_items, features)
    _score_funding(score_items, risks, features)
    _score_omo(score_items, features)
    _score_futures(score_items, features)
    _score_text(score_items, features)
    _score_macro(score_items, features)

    if features.get("spread_30y_10y") is not None and features["spread_30y_10y"] > 0.35:
        risks.append("30Y-10Y 曲线偏陡，可能反映超长端供给或期限溢价扰动。")
    risks.append("该信号是研究型规则判断，不是价格预测或交易建议。")

    score = sum(float(item["score"]) for item in score_items)
    if score >= 2:
        view = "bullish"
    elif score <= -2:
        view = "bearish"
    else:
        view = "neutral"

    drivers = [item["reason"] for item in score_items if item["score"] != 0]
    if not drivers:
        drivers.append("全部评分维度均处于中性区间。")

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


def _score_rates(score_items: list[dict[str, Any]], features: dict[str, Any]) -> None:
    value = features.get("yield_10y_change")
    if value is None:
        _add_score(score_items, "利率方向", 0, "缺少上一期 10Y 收益率，利率方向暂不计分。")
    elif value <= -0.01:
        _add_score(score_items, "利率方向", 2, "10Y 收益率明显下行，支撑国债期货。")
    elif value >= 0.01:
        _add_score(score_items, "利率方向", -2, "10Y 收益率明显上行，压制国债期货。")
    else:
        _add_score(score_items, "利率方向", 0, "10Y 收益率变化未超过方向阈值。")


def _score_curve(score_items: list[dict[str, Any]], features: dict[str, Any]) -> None:
    value = features.get("spread_10y_2y")
    if value is None:
        _add_score(score_items, "曲线形态", 0, "缺少 10Y-2Y 利差，曲线形态暂不计分。")
    elif value < 0.35:
        _add_score(score_items, "曲线形态", 0.5, "10Y-2Y 利差偏窄，期限溢价压力有限。")
    elif value > 0.75:
        _add_score(score_items, "曲线形态", -0.5, "10Y-2Y 利差偏宽，曲线陡峭化压力较高。")
    else:
        _add_score(score_items, "曲线形态", 0, "10Y-2Y 利差处于中性区间。")


def _score_funding(score_items: list[dict[str, Any]], risks: list[str], features: dict[str, Any]) -> None:
    value = features.get("dr007_change")
    if value is None:
        _add_score(score_items, "资金面", 0, "缺少上一交易日 DR007，资金面变化项暂不计分。")
        risks.append("缺少上一交易日 DR007，资金面变化项暂不计分。")
    elif value <= -0.03:
        _add_score(score_items, "资金面", 1, "DR007 下行，银行间资金面边际转松。")
    elif value >= 0.03:
        _add_score(score_items, "资金面", -1, "DR007 上行，银行间资金面边际收紧。")
    else:
        _add_score(score_items, "资金面", 0, "DR007 变化未超过方向阈值。")


def _score_omo(score_items: list[dict[str, Any]], features: dict[str, Any]) -> None:
    value = features.get("omo_net_injection_amount")
    if value is None:
        _add_score(score_items, "公开市场操作", 0, "缺少公开市场操作数据，OMO 暂不计分。")
    elif value >= 500:
        _add_score(score_items, "公开市场操作", 1, f"公开市场净投放 {value:.0f} 亿元，资金面支持偏多。")
    elif value <= -500:
        _add_score(score_items, "公开市场操作", -1, f"公开市场净回笼 {abs(value):.0f} 亿元，资金面压力偏空。")
    else:
        _add_score(score_items, "公开市场操作", 0, "净投放/净回笼规模未达到方向阈值。")


def _score_futures(score_items: list[dict[str, Any]], features: dict[str, Any]) -> None:
    ret = features.get("avg_futures_return")
    volume_change = features.get("avg_volume_change")
    if ret is None or volume_change is None:
        _add_score(score_items, "期货量价", 0, "缺少上一期成交量或当日期货收益率，量价项暂不计分。")
    elif ret > 0 and volume_change > 0:
        _add_score(score_items, "期货量价", 1, "期货上涨且成交活跃度提高，量价配合偏积极。")
    elif ret < 0 and volume_change > 0:
        _add_score(score_items, "期货量价", -1, "期货下跌且成交活跃度提高，量价配合偏消极。")
    else:
        _add_score(score_items, "期货量价", 0, "期货收益率和成交活跃度未形成同向确认。")


def _score_text(score_items: list[dict[str, Any]], features: dict[str, Any]) -> None:
    value = features.get("avg_ai_sentiment_score")
    if value is None:
        _add_score(score_items, "文本信号", 0, "缺少政策/新闻文本信号，文本项暂不计分。")
    elif value > 0.25:
        _add_score(score_items, "文本信号", 1, "政策与新闻文本信号整体偏多。")
    elif value < -0.25:
        _add_score(score_items, "文本信号", -1, "政策与新闻文本信号整体偏空。")
    else:
        _add_score(score_items, "文本信号", 0, "新闻文本整体处于中性区间。")


def _score_macro(score_items: list[dict[str, Any]], features: dict[str, Any]) -> None:
    macro = features.get("details", {}).get("macro_indicators", {})
    pmi = macro.get("PMI_MFG")
    if pmi is None:
        _add_score(score_items, "宏观基本面", 0, "缺少制造业 PMI，宏观基本面暂不计分。")
    elif pmi < 49.5:
        _add_score(score_items, "宏观基本面", 0.5, f"制造业 PMI {pmi:.1f} 低于荣枯线，基本面偏弱支撑债市。")
    elif pmi > 50.5:
        _add_score(score_items, "宏观基本面", -0.5, f"制造业 PMI {pmi:.1f} 高于荣枯线，基本面偏强压制债市。")
    else:
        _add_score(score_items, "宏观基本面", 0, f"制造业 PMI {pmi:.1f} 处于荣枯线附近，宏观基本面中性。")


def _add_score(score_items: list[dict[str, Any]], category: str, score: float, reason: str) -> None:
    score_items.append({"category": category, "score": score, "reason": reason})


def _summarize_score_items(score_items: list[dict[str, Any]]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for item in score_items:
        summary[item["category"]] = summary.get(item["category"], 0.0) + float(item["score"])
    return summary

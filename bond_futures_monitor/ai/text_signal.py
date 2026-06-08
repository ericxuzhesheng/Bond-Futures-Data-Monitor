"""Deterministic text-to-signal classifier."""

from __future__ import annotations

from typing import Any

from bond_futures_monitor.ai.schema import AFFECTED_MATURITIES, BOND_IMPACTS, CONTRACTS, EVENT_TYPES


MODEL_NAME = "mock-rule-based-text-signal-v1"


def classify_news_item(news: dict[str, Any]) -> dict[str, Any]:
    """Convert one policy/news item into a structured fixed-income signal."""

    text = f"{news.get('title', '')} {news.get('content', '')}".lower()

    if any(term in text for term in ["liquidity", "funding", "dr007", "shibor", "injection", "流动性", "资金", "投放"]):
        result = {
            "event_type": "funding_liquidity",
            "summary": "资金面边际宽松，对债券久期资产形成支撑。",
            "bond_impact": "bullish",
            "affected_maturity": "full_curve",
            "related_contracts": ["TS", "TF", "T", "TL"],
            "confidence": 4,
            "reasoning": "流动性投放 -> 资金压力下降 -> 收益率上行压力缓和 -> 国债期货获得支撑。",
        }
    elif any(term in text for term in ["supply", "issuance", "special bond", "government bond", "供给", "发行", "地方政府债"]):
        result = {
            "event_type": "bond_supply",
            "summary": "债券供给增加可能压制长久期情绪。",
            "bond_impact": "bearish",
            "affected_maturity": "long_end",
            "related_contracts": ["T", "TL"],
            "confidence": 4,
            "reasoning": "供给增加 -> 久期吸收压力上升 -> 收益率存在上行压力 -> 长端国债期货承压。",
        }
    elif any(term in text for term in ["inflation", "cpi", "ppi", "通胀"]):
        result = {
            "event_type": "inflation",
            "summary": "通胀信息可能影响降息预期。",
            "bond_impact": "neutral",
            "affected_maturity": "full_curve",
            "related_contracts": ["TF", "T", "TL"],
            "confidence": 3,
            "reasoning": "通胀信号 -> 政策预期重估 -> 收益率变化 -> 国债期货重新定价。",
        }
    else:
        result = {
            "event_type": "other",
            "summary": "文本暂未提供明确的利率债方向信号。",
            "bond_impact": "neutral",
            "affected_maturity": "unclear",
            "related_contracts": [],
            "confidence": 2,
            "reasoning": "事件传导路径不清晰 -> 对收益率影响有限 -> 国债期货含义偏中性。",
        }

    result["news_id"] = news.get("id")
    result["date"] = news["date"]
    result["model_name"] = MODEL_NAME
    validate_signal(result)
    return result


def sentiment_score(bond_impact: str) -> int:
    if bond_impact == "bullish":
        return 1
    if bond_impact == "bearish":
        return -1
    return 0


def validate_signal(signal: dict[str, Any]) -> None:
    if signal["event_type"] not in EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {signal['event_type']}")
    if signal["bond_impact"] not in BOND_IMPACTS:
        raise ValueError(f"Invalid bond_impact: {signal['bond_impact']}")
    if signal["affected_maturity"] not in AFFECTED_MATURITIES:
        raise ValueError(f"Invalid affected_maturity: {signal['affected_maturity']}")
    if not 1 <= int(signal["confidence"]) <= 5:
        raise ValueError("confidence must be between 1 and 5")
    invalid_contracts = set(signal["related_contracts"]) - CONTRACTS
    if invalid_contracts:
        raise ValueError(f"Invalid contracts: {sorted(invalid_contracts)}")

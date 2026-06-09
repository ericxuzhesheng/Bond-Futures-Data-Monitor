"""Text-to-signal classifier for fixed-income policy/news items."""

from __future__ import annotations

import json
import os
from typing import Any

from bond_futures_monitor.ai.schema import AFFECTED_MATURITIES, BOND_IMPACTS, CONTRACTS, EVENT_TYPES


_RULE_MODEL = "rule-based-text-signal-v3"
_LLM_MODEL = "claude-haiku-4-5-20251001"


def classify_news_item(news: dict[str, Any]) -> dict[str, Any]:
    """Convert one real news item into a structured fixed-income signal."""

    text = f"{news.get('title', '')} {news.get('content', '')}"
    result = _classify_with_llm(text) or _classify_with_rules(text)
    result["news_id"] = news.get("id")
    result["date"] = news["date"]
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


def _classify_with_llm(text: str) -> dict[str, Any] | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None

    all_event_types = "|".join(sorted(EVENT_TYPES))
    prompt = f"""你是中国利率债研究助理。请把下面政策/新闻文本转成结构化国债期货信号，只输出 JSON。

文本：
{text[:1200]}

字段要求：
{{
  "event_type": "{all_event_types}之一",
  "summary": "不超过50字的中文摘要",
  "bond_impact": "bullish|bearish|neutral",
  "affected_maturity": "short_end|belly|long_end|full_curve|unclear",
  "related_contracts": ["TS","TF","T","TL"] 中受影响的合约,
  "confidence": 1到5的整数,
  "reasoning": "事件到收益率再到国债期货的传导链条，不超过80字"
}}"""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            content = parts[1]
            raw = content[4:].lstrip() if content.startswith("json") else content.lstrip()
        result: dict[str, Any] = json.loads(raw)
    except Exception:
        return None

    result["event_type"] = result.get("event_type") if result.get("event_type") in EVENT_TYPES else "other"
    result["bond_impact"] = result.get("bond_impact") if result.get("bond_impact") in BOND_IMPACTS else "neutral"
    result["affected_maturity"] = (
        result.get("affected_maturity") if result.get("affected_maturity") in AFFECTED_MATURITIES else "unclear"
    )
    result["related_contracts"] = [c for c in result.get("related_contracts", []) if c in CONTRACTS]
    result["confidence"] = max(1, min(5, int(result.get("confidence", 2))))
    result["model_name"] = _LLM_MODEL
    return result


def _classify_with_rules(text: str) -> dict[str, Any]:
    t = text.lower()

    if _has(t, "降准", "降息", "净投放", "呵护流动性", "超额续作", "easing", "rate cut"):
        return _sig(
            "monetary_policy",
            "bullish",
            "full_curve",
            ["TS", "TF", "T", "TL"],
            4,
            "货币政策或流动性边际偏宽",
            "宽松信号降低无风险利率预期，支撑国债期货价格。",
        )
    if _has(t, "加息", "回笼", "净回笼", "收紧", "缩表", "tighten", "rate hike", "drain"):
        return _sig(
            "monetary_policy",
            "bearish",
            "full_curve",
            ["TS", "TF", "T", "TL"],
            4,
            "货币政策或流动性边际收紧",
            "资金回笼推升利率预期，国债期货承压。",
        )
    if _has(t, "dr007", "shibor", "资金利率", "银行间", "流动性", "repo", "funding"):
        return _sig(
            "funding_liquidity",
            "neutral",
            "full_curve",
            ["TS", "TF", "T", "TL"],
            3,
            "资金面相关信息需要结合利率方向判断",
            "资金价格影响持仓成本，方向取决于利率上行或下行。",
        )
    if _has(t, "地方债", "专项债", "国债发行", "特别国债", "债券供给", "发行规模", "supply", "issuance"):
        impact = "bearish" if _has(t, "增加", "扩大", "放量", "上升", "提速", "increase", "large") else "neutral"
        return _sig(
            "bond_supply",
            impact,
            "long_end",
            ["T", "TL"],
            4 if impact == "bearish" else 3,
            "债券供给信息影响长端利率",
            "供给增加会提高长端吸收压力，长端国债期货更敏感。",
        )
    if _has(t, "cpi", "ppi", "通胀", "物价", "inflation", "deflation"):
        if _has(t, "上升", "反弹", "高于", "超预期", "rise", "higher"):
            return _sig("inflation", "bearish", "full_curve", ["TF", "T", "TL"], 3, "通胀压力上升", "通胀抬升压缩宽松空间，利率债偏空。")
        if _has(t, "回落", "低于", "走弱", "通缩", "below", "weak", "lower"):
            return _sig("inflation", "bullish", "full_curve", ["TF", "T", "TL"], 3, "通胀压力回落", "通胀走弱提高宽松预期，利率债偏多。")
    if _has(t, "gdp", "pmi", "社融", "信贷", "经济", "制造业", "增长", "growth", "economy", "credit"):
        if _has(t, "超预期", "改善", "回升", "加快", "strong", "beat", "recover"):
            return _sig("macro_growth", "bearish", "long_end", ["T", "TL"], 3, "增长数据偏强", "经济修复削弱宽松必要性，长端收益率有上行压力。")
        if _has(t, "低于预期", "走弱", "放缓", "下滑", "weak", "miss", "slow"):
            return _sig("macro_growth", "bullish", "long_end", ["T", "TL"], 3, "增长数据偏弱", "基本面走弱提升宽松预期，支撑长端国债期货。")
    if _has(t, "财政", "赤字", "预算", "财政刺激", "fiscal", "deficit", "stimulus"):
        return _sig("fiscal_policy", "bearish", "long_end", ["T", "TL"], 3, "财政扩张相关信息", "财政扩张通常伴随债券供给压力，长端期货偏空。")
    if _has(t, "美联储", "美债", "fed", "us treasury", "海外利率", "global rate"):
        return _sig("overseas_rates", "neutral", "long_end", ["T", "TL"], 2, "海外利率扰动", "海外利率通过全球期限溢价影响国内长端。")
    if _has(t, "避险", "股市下跌", "风险偏好", "risk-off", "risk appetite", "safe haven"):
        return _sig("risk_sentiment", "bullish", "long_end", ["T", "TL"], 3, "风险偏好变化", "避险情绪提升会增加利率债配置需求。")

    return _sig("other", "neutral", "unclear", [], 2, "文本未给出明确利率债方向", "传导链条不清晰，暂不形成方向性判断。")


def _has(text: str, *keywords: str) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def _sig(
    event_type: str,
    bond_impact: str,
    affected_maturity: str,
    related_contracts: list[str],
    confidence: int,
    summary: str,
    reasoning: str,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "summary": summary,
        "bond_impact": bond_impact,
        "affected_maturity": affected_maturity,
        "related_contracts": related_contracts,
        "confidence": confidence,
        "reasoning": reasoning,
        "model_name": _RULE_MODEL,
    }

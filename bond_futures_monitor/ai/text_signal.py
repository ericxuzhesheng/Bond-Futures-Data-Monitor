"""Text-to-signal classifier: rule-based with optional Claude LLM backend.

Set ANTHROPIC_API_KEY to enable real LLM analysis; otherwise falls back to
the deterministic rule-based classifier which encodes the analyst's own
keyword-to-signal mapping for Chinese fixed-income markets.
"""

from __future__ import annotations

import json
import os
from statistics import mean
from typing import Any

from bond_futures_monitor.ai.schema import AFFECTED_MATURITIES, BOND_IMPACTS, CONTRACTS, EVENT_TYPES


_RULE_MODEL = "rule-based-text-signal-v2"
_LLM_MODEL = "claude-haiku-4-5-20251001"


def classify_news_item(news: dict[str, Any]) -> dict[str, Any]:
    """Convert one policy/news item into a structured fixed-income signal."""
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


# ──────────────────────────────────────────────────────────────────────────────
# LLM backend (optional)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_with_llm(text: str) -> dict[str, Any] | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None

    all_event_types = "|".join(sorted(EVENT_TYPES))
    prompt = f"""你是固定收益量化研究助手，专注中国利率债市场。请分析以下政策/新闻文本，输出结构化信号。

文本：
{text[:1200]}

请严格按照以下JSON格式输出（不要任何额外文字或markdown代码块）：
{{
  "event_type": "{all_event_types}之一",
  "summary": "一句话中文摘要，不超过50字",
  "bond_impact": "bullish（看多利率债）| bearish（看空利率债）| neutral",
  "affected_maturity": "short_end（1-2Y）| belly（5Y）| long_end（10-30Y）| full_curve（全曲线）| unclear",
  "related_contracts": ["TS","TF","T","TL"]中受影响合约的子集,
  "confidence": 1到5的整数（传导越清晰越高）,
  "reasoning": "传导链条：事件->收益率影响->国债期货含义，不超过60字"
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
            raw = parts[1][4:] if parts[1].startswith("json") else parts[1]
        result: dict[str, Any] = json.loads(raw)
        if result.get("event_type") not in EVENT_TYPES:
            result["event_type"] = "other"
        if result.get("bond_impact") not in BOND_IMPACTS:
            result["bond_impact"] = "neutral"
        if result.get("affected_maturity") not in AFFECTED_MATURITIES:
            result["affected_maturity"] = "unclear"
        result["related_contracts"] = [c for c in result.get("related_contracts", []) if c in CONTRACTS]
        result["confidence"] = max(1, min(5, int(result.get("confidence", 2))))
        result["model_name"] = _LLM_MODEL
        return result
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Rule-based classifier (fallback — encodes analyst domain knowledge)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_with_rules(text: str) -> dict[str, Any]:
    t = text.lower()

    # 1. Monetary policy
    _MP = ["货币政策", "央行", "人民银行", "mlf", "lpr", "逆回购", "公开市场", "准备金", "降准",
           "降息", "加息", "monetary policy", "pboc", "open market", "reserve requirement"]
    if any(k in t for k in _MP):
        _EASE = ["降息", "降准", "宽松", "净投放", "呵护", "超额续作", "rate cut", "easing", "cut lpr"]
        _TIGHT = ["加息", "回笼", "收紧", "缩表", "rate hike", "tighten", "drain", "withdraw"]
        if any(k in t for k in _EASE):
            return _sig("monetary_policy", "bullish", "full_curve", ["TS", "TF", "T", "TL"], 4,
                        "货币政策宽松信号，利率下行预期升温。",
                        "降息/降准/净投放 -> 无风险利率下行 -> 国债期货获得支撑。")
        if any(k in t for k in _TIGHT):
            return _sig("monetary_policy", "bearish", "full_curve", ["TS", "TF", "T", "TL"], 4,
                        "货币政策收紧信号，利率上行压力加大。",
                        "回笼/收紧 -> 无风险利率上行预期 -> 国债期货承压。")
        return _sig("monetary_policy", "neutral", "full_curve", ["TF", "T"], 3,
                    "货币政策动向，方向尚不明确。",
                    "货币政策事件 -> 方向中性 -> 等待进一步信号。")

    # 2. Funding/liquidity
    _FL = ["流动性", "资金", "dr007", "dr001", "r007", "shibor", "回购利率", "银行间",
           "liquidity", "funding", "interbank", "repo", "资金面"]
    if any(k in t for k in _FL):
        _LOOSE = ["宽松", "充裕", "改善", "回落", "下行", "下降", "净投放", "loose", "ample", "ease", "lower"]
        _TIGHT2 = ["紧张", "收紧", "上行", "上升", "tight", "tighten", "pressure", "rise", "higher"]
        if any(k in t for k in _LOOSE):
            return _sig("funding_liquidity", "bullish", "full_curve", ["TS", "TF", "T", "TL"], 4,
                        "资金面边际宽松，对债券久期资产形成支撑。",
                        "资金利率下行/净投放 -> 持仓成本降低 -> 国债期货获得支撑。")
        if any(k in t for k in _TIGHT2):
            return _sig("funding_liquidity", "bearish", "full_curve", ["TS", "TF", "T", "TL"], 4,
                        "资金面边际收紧，债券持仓成本上升。",
                        "资金利率上行 -> 持仓成本压力加大 -> 国债期货承压。")
        return _sig("funding_liquidity", "neutral", "full_curve", ["TS", "TF", "T", "TL"], 3,
                    "资金面动向，方向中性。",
                    "资金面信号 -> 影响方向不明 -> 中性观望。")

    # 3. Bond supply
    _BS = ["发行", "供给", "地方政府债", "国债发行", "特别国债", "新债", "债券供给", "债券发行",
           "supply", "issuance", "government bond issue"]
    if any(k in t for k in _BS):
        _BIG = ["增加", "扩大", "较大", "创新高", "上升", "放量", "increase", "large", "surge", "rise"]
        if any(k in t for k in _BIG):
            return _sig("bond_supply", "bearish", "long_end", ["T", "TL"], 4,
                        "债券供给增加，长端利率存在上行压力。",
                        "发行规模扩大 -> 久期供给吸收压力 -> 长端收益率上行 -> 长端期货承压。")
        return _sig("bond_supply", "neutral", "long_end", ["T", "TL"], 3,
                    "债券供给动向，规模及影响待定。",
                    "供给事件 -> 规模不明 -> 对长端期货影响偏中性。")

    # 4. Inflation
    _INF = ["通胀", "cpi", "ppi", "物价", "通货膨胀", "inflation", "deflation", "通缩", "price index"]
    if any(k in t for k in _INF):
        _HIGH = ["上升", "超预期", "高于", "通胀压力", "反弹", "rise", "higher", "exceed", "beat", "rebound"]
        _LOW = ["低于", "走弱", "通缩", "下行", "deflation", "below", "weak", "lower", "miss"]
        if any(k in t for k in _HIGH):
            return _sig("inflation", "bearish", "full_curve", ["TF", "T", "TL"], 3,
                        "通胀上升，货币宽松空间收窄，收益率下行受阻。",
                        "通胀高于预期 -> 降息空间压缩 -> 长端收益率下行受阻 -> 国债期货偏空。")
        if any(k in t for k in _LOW):
            return _sig("inflation", "bullish", "full_curve", ["TF", "T", "TL"], 3,
                        "通胀低迷，货币宽松预期升温，对利率债形成支撑。",
                        "通胀低于预期 -> 降息空间打开 -> 收益率下行预期 -> 国债期货偏多。")
        return _sig("inflation", "neutral", "full_curve", ["TF", "T"], 2,
                    "通胀数据公布，方向待定。",
                    "通胀事件 -> 影响货币政策预期 -> 方向中性。")

    # 5. Macro growth
    _MG = ["gdp", "经济", "pmi", "工业增加值", "社融", "信贷", "增长", "复苏", "制造业",
           "growth", "economy", "industrial", "credit", "recovery", "manufacturing"]
    if any(k in t for k in _MG):
        _STRONG = ["超预期", "加速", "强劲", "改善", "回升", "好于", "beat", "strong", "accelerate", "recover"]
        _WEAK = ["低于预期", "放缓", "走弱", "下滑", "miss", "weak", "slow", "decelerate", "disappoint"]
        if any(k in t for k in _STRONG):
            return _sig("macro_growth", "bearish", "long_end", ["T", "TL"], 3,
                        "经济数据走强，长端利率存在上行压力。",
                        "经济超预期 -> 货币宽松必要性降低 -> 长端收益率上行 -> 长端期货承压。")
        if any(k in t for k in _WEAK):
            return _sig("macro_growth", "bullish", "long_end", ["T", "TL"], 3,
                        "经济走弱，宽松预期升温，对长久期利率债形成支撑。",
                        "经济不及预期 -> 降息/宽松预期升温 -> 长端收益率下行 -> 长端期货获支撑。")
        return _sig("macro_growth", "neutral", "belly", ["TF", "T"], 2,
                    "宏观经济数据公布，方向中性。",
                    "宏观数据事件 -> 方向不明 -> 等待进一步信号。")

    # 6. Fiscal policy
    _FP = ["财政", "赤字", "专项债", "一般公共预算", "转移支付", "财政刺激",
           "fiscal", "deficit", "stimulus", "budget", "government spending", "special bond"]
    if any(k in t for k in _FP):
        _EXPAND = ["扩张", "扩大", "加码", "刺激", "增加", "扩赤字", "expand", "stimulus", "widen", "increase"]
        if any(k in t for k in _EXPAND):
            return _sig("fiscal_policy", "bearish", "long_end", ["T", "TL"], 3,
                        "财政扩张推升债券供给，长端利率存在上行压力。",
                        "财政扩张 -> 国债/地方债发行增加 -> 久期供给压力 -> 长端期货承压。")
        return _sig("fiscal_policy", "neutral", "long_end", ["T", "TL"], 2,
                    "财政政策动向，影响方向待定。",
                    "财政政策事件 -> 供需影响待定 -> 方向中性。")

    # 7. Overseas rates
    _OV = ["美联储", "fed", "美债", "us treasury", "海外利率", "全球利率",
           "federal reserve", "ecb", "overseas rate", "global rate", "外资"]
    if any(k in t for k in _OV):
        _US_FALL = ["美债收益率下行", "美联储降息", "fed cut", "treasury yield fall", "risk-off", "美债走强"]
        _US_RISE = ["美债收益率上行", "美联储加息", "fed hike", "treasury yield rise", "美债走弱"]
        if any(k in t for k in _US_FALL):
            return _sig("overseas_rates", "bullish", "long_end", ["T", "TL"], 3,
                        "海外利率下行，正向溢出效应支撑国内长端。",
                        "美债收益率下行 -> 全球无风险利率中枢下移 -> 国内长端收益率下行共振 -> 长端期货偏多。")
        if any(k in t for k in _US_RISE):
            return _sig("overseas_rates", "bearish", "long_end", ["T", "TL"], 3,
                        "海外利率上行，对国内长端利率形成扰动。",
                        "美债收益率上行 -> 全球利率中枢上移 -> 国内长端收益率存在跟涨压力 -> 长端期货承压。")
        return _sig("overseas_rates", "neutral", "long_end", ["T", "TL"], 2,
                    "海外利率市场动向，影响方向待定。",
                    "海外利率事件 -> 传导路径不确定 -> 方向中性。")

    # 8. Risk sentiment
    _RS = ["风险偏好", "避险", "股市下跌", "权益市场", "北向资金",
           "risk appetite", "risk-off", "risk-on", "equity selloff", "safe haven"]
    if any(k in t for k in _RS):
        _RISK_OFF = ["下跌", "避险", "下降", "撤出", "risk-off", "selloff", "retreat", "flight"]
        if any(k in t for k in _RISK_OFF):
            return _sig("risk_sentiment", "bullish", "long_end", ["T", "TL"], 3,
                        "风险偏好下降，资金流向利率债避险。",
                        "股市下跌/风险偏好下行 -> 资金转向利率债 -> 收益率下行 -> 长端期货偏多。")
        return _sig("risk_sentiment", "neutral", "unclear", [], 2,
                    "风险情绪变化，对利率债方向影响待定。",
                    "风险情绪事件 -> 传导路径不明 -> 方向中性。")

    # Default
    return _sig("other", "neutral", "unclear", [], 2,
                "文本暂未提供明确的利率债方向信号。",
                "事件传导路径不清晰 -> 对收益率影响有限 -> 国债期货含义偏中性。")


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

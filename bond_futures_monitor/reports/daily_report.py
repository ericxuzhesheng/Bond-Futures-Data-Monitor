"""Markdown daily report generation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def generate_daily_report(conn: sqlite3.Connection, run_date: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    futures = conn.execute("SELECT * FROM futures_quotes WHERE date = ? ORDER BY contract", (run_date,)).fetchall()
    yields = conn.execute("SELECT * FROM bond_yields WHERE date = ? ORDER BY tenor", (run_date,)).fetchall()
    funding = conn.execute("SELECT * FROM funding_rates WHERE date = ? ORDER BY rate_name", (run_date,)).fetchall()
    ai = conn.execute("SELECT * FROM ai_text_signals WHERE date = ? ORDER BY id", (run_date,)).fetchall()
    signal = conn.execute("SELECT * FROM daily_market_signals WHERE date = ?", (run_date,)).fetchone()

    if signal is None:
        raise ValueError(f"No daily market signal found for {run_date}")

    key_drivers = json.loads(signal["key_drivers"])
    risk_notes = json.loads(signal["risk_notes"])
    view_label = _market_view_label(signal["market_view"])

    lines = [
        f"# 中国国债期货每日监控报告 - {run_date}",
        "",
        "## 每日市场判断",
        f"- 市场观点：**{view_label}**",
        f"- 综合评分：**{signal['total_score']:.2f}**",
        "",
        "## 国债期货概览",
        "| 合约 | 收盘价 | 日收益率 | 成交量 | 持仓量 |",
        "|---|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row['contract']} | {row['close_price']:.3f} | {row['daily_return']:.4%} | "
        f"{row['volume']:.0f} | {row['open_interest']:.0f} |"
        for row in futures
    )
    lines.extend(["", "## 收益率曲线概览", "| 期限 | 收益率 |", "|---|---:|"])
    lines.extend(f"| {row['tenor']} | {row['yield_value']:.3f}% |" for row in yields)
    lines.extend(["", "## 资金面概览", "| 指标 | 利率 |", "|---|---:|"])
    lines.extend(f"| {row['rate_name']} | {row['rate_value']:.3f}% |" for row in funding)
    lines.extend(["", "## AI 政策与新闻解读"])
    seen_ai: set[tuple[str, str, str]] = set()
    for row in ai:
        dedupe_key = (row["event_type"], row["summary"], row["bond_impact"])
        if dedupe_key in seen_ai:
            continue
        seen_ai.add(dedupe_key)
        contracts = ", ".join(json.loads(row["related_contracts"])) or "无"
        lines.extend(
            [
                f"### {_event_type_label(row['event_type'])}",
                f"- 摘要：{row['summary']}",
                f"- 债券影响：**{_impact_label(row['bond_impact'])}**",
                f"- 影响期限：{_maturity_label(row['affected_maturity'])}",
                f"- 相关合约：{contracts}",
                f"- 置信度：{row['confidence']}/5",
                f"- 推理链条：{row['reasoning']}",
                "",
            ]
        )
    lines.extend(["## 核心驱动"])
    lines.extend(f"- {item}" for item in key_drivers)
    lines.extend(["", "## 风险提示"])
    lines.extend(f"- {item}" for item in risk_notes)
    lines.extend(
        [
            "",
            "## 方法说明",
            "AI 层是文本到信号的结构化引擎，用于把政策和新闻文本转化为固定收益研究信号；它不是黑箱价格预测器。",
            "",
        ]
    )

    path = output_dir / f"{run_date}_daily_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _market_view_label(value: str) -> str:
    return {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(value, value)


def _impact_label(value: str) -> str:
    return {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(value, value)


def _maturity_label(value: str) -> str:
    return {
        "short_end": "短端",
        "belly": "中段",
        "long_end": "长端",
        "full_curve": "全曲线",
        "unclear": "不明确",
    }.get(value, value)


def _event_type_label(value: str) -> str:
    return {
        "monetary_policy": "货币政策",
        "fiscal_policy": "财政政策",
        "macro_growth": "宏观增长",
        "inflation": "通胀",
        "bond_supply": "债券供给",
        "funding_liquidity": "资金流动性",
        "risk_sentiment": "风险偏好",
        "overseas_rates": "海外利率",
        "other": "其他",
    }.get(value, value)

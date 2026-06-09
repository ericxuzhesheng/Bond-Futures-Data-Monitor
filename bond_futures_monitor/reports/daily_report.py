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
    news = conn.execute("SELECT * FROM policy_news WHERE date = ? ORDER BY id", (run_date,)).fetchall()
    ai = conn.execute(
        """
        SELECT signal.*
        FROM ai_text_signals AS signal
        JOIN (
            SELECT news_id, MAX(id) AS latest_id
            FROM ai_text_signals
            WHERE date = ?
            GROUP BY news_id
        ) AS latest
          ON latest.latest_id = signal.id
        ORDER BY signal.id
        """,
        (run_date,),
    ).fetchall()
    signal = conn.execute("SELECT * FROM daily_market_signals WHERE date = ?", (run_date,)).fetchone()
    if signal is None:
        raise ValueError(f"No daily market signal found for {run_date}")

    key_drivers = json.loads(signal["key_drivers"])
    risk_notes = json.loads(signal["risk_notes"])
    signal_details = json.loads(signal["details_json"])
    score_items = signal_details.get("score_items", [])
    feature_snapshot = signal_details.get("feature_snapshot", {})
    feature_details = feature_snapshot.get("details", {})
    feature_groups = feature_details.get("feature_groups", {})
    data_sources = feature_details.get("data_sources", {})

    lines = [
        f"# 中国国债期货每日真实数据监控报告 - {run_date}",
        "",
        "## 每日市场判断",
        f"- 市场观点：**{_market_view_label(signal['market_view'])}**",
        f"- 综合评分：**{signal['total_score']:.2f}**",
        "",
        "## 数据真实性检查",
        f"- 国债期货合约：{len(futures)} 条",
        f"- 国债收益率期限：{len(yields)} 条",
        f"- 资金利率：{len(funding)} 条",
        f"- 政策/新闻文本：{len(news)} 条",
        f"- 当日真实数据合计：{len(futures) + len(yields) + len(funding) + len(news)} 条",
        "- 生产流程禁止非真实数据；覆盖不足会直接失败。",
        "",
        "## 评分拆解",
        "| 维度 | 分数 | 判断依据 |",
        "|---|---:|---|",
    ]
    if score_items:
        lines.extend(f"| {item['category']} | {float(item['score']):.2f} | {item['reason']} |" for item in score_items)
    else:
        lines.append("| 无 | 0.00 | 当日没有触发明确方向规则。 |")

    lines.extend(["", "## 特征面板", "| 分组 | 指标 | 数值 |", "|---|---|---:|"])
    lines.extend(_feature_panel_rows(feature_groups))

    lines.extend(["", "## 数据来源", "| 数据类别 | 来源 |", "|---|---|"])
    lines.extend(_data_source_rows(data_sources))

    lines.extend(["", "## 国债期货概览", "| 合约 | 收盘价 | 日收益率 | 成交量 | 持仓量 |", "|---|---:|---:|---:|---:|"])
    lines.extend(
        f"| {row['contract']} | {row['close_price']:.3f} | {row['daily_return']:.4%} | "
        f"{row['volume']:.0f} | {row['open_interest']:.0f} |"
        for row in futures
    )

    lines.extend(["", "## 收益率曲线概览", "| 期限 | 收益率 |", "|---|---:|"])
    lines.extend(f"| {row['tenor']} | {row['yield_value']:.3f}% |" for row in yields)

    lines.extend(["", "## 资金面概览", "| 指标 | 利率 |", "|---|---:|"])
    lines.extend(f"| {row['rate_name']} | {row['rate_value']:.3f}% |" for row in funding)

    directional_ai = [
        row
        for row in ai
        if not (row["event_type"] == "other" and row["bond_impact"] == "neutral" and int(row["confidence"]) <= 2)
    ]
    neutral_other_count = len(ai) - len(directional_ai)

    lines.extend(["", "## 政策与新闻结构化解读"])
    if neutral_other_count:
        lines.append(f"- {neutral_other_count} 条新闻未形成明确利率债方向，已归入中性背景信息，不逐条展开。")
        lines.append("")
    for row in directional_ai:
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
            "文本层用于把真实政策/新闻转成固定 schema 的利率债研究信号；规则评分用于解释当日数据含义，不直接预测价格。",
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


def _feature_panel_rows(feature_groups: dict) -> list[str]:
    labels = {
        "yield_10y_change": "10Y 收益率变化",
        "yield_30y_change": "30Y 收益率变化",
        "spread_10y_2y": "10Y-2Y 利差",
        "spread_30y_10y": "30Y-10Y 利差",
        "dr007_change": "DR007 变化",
        "available_rates": "可用资金利率",
        "avg_futures_return": "期货平均日收益率",
        "avg_volume_change": "成交活跃度变化",
        "contract_count": "覆盖合约数量",
        "avg_ai_sentiment_score": "文本情绪均值",
        "signal_count": "文本信号数量",
    }
    group_labels = {"rates": "利率", "funding": "资金面", "futures": "期货量价", "text": "文本"}
    rows: list[str] = []
    for group, values in feature_groups.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            rows.append(f"| {group_labels.get(group, group)} | {labels.get(key, key)} | {_format_feature_value(value)} |")
    return rows or ["| 无 | 无 | 缺失 |"]


def _data_source_rows(data_sources: dict) -> list[str]:
    labels = {
        "futures": "国债期货",
        "yield_curve": "收益率曲线",
        "funding": "资金利率",
        "policy_news": "政策/新闻",
    }
    rows = []
    for key, values in data_sources.items():
        source = ", ".join(values) if isinstance(values, list) else str(values)
        rows.append(f"| {labels.get(key, key)} | {source or '无'} |")
    return rows or ["| 无 | 无 |"]


def _format_feature_value(value) -> str:
    if value is None:
        return "缺失"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "无"
    return str(value)

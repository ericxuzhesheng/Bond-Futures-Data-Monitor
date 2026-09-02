"""Markdown daily report generation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bond_futures_monitor.reports.charts import generate_report_charts


def generate_daily_report(conn: sqlite3.Connection, run_date: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    futures = conn.execute("SELECT * FROM futures_quotes WHERE date = ? ORDER BY contract", (run_date,)).fetchall()
    yields = conn.execute("SELECT * FROM bond_yields WHERE date = ? ORDER BY tenor", (run_date,)).fetchall()
    funding = conn.execute("SELECT * FROM funding_rates WHERE date = ? ORDER BY rate_name", (run_date,)).fetchall()
    omo = conn.execute(
        "SELECT * FROM open_market_operations WHERE date = ? ORDER BY operation_type, tenor_days",
        (run_date,),
    ).fetchall()
    news = conn.execute("SELECT * FROM policy_news WHERE date = ? ORDER BY id", (run_date,)).fetchall()
    macro = conn.execute("SELECT * FROM macro_indicators WHERE date = ? ORDER BY indicator", (run_date,)).fetchall()
    macro_history = conn.execute(
        "SELECT * FROM macro_history WHERE date = ? ORDER BY period DESC, indicator", (run_date,)
    ).fetchall()
    treasury_calendar = conn.execute(
        "SELECT * FROM treasury_issuance_calendar WHERE date = ? ORDER BY auction_date, tenor", (run_date,)
    ).fetchall()
    curve_comparison = conn.execute(
        "SELECT * FROM yield_curve_comparisons WHERE date = ? ORDER BY CAST(tenor AS INTEGER)", (run_date,)
    ).fetchall()
    collection_status = {
        row["dataset"]: dict(row)
        for row in conn.execute("SELECT * FROM collection_status WHERE date = ? ORDER BY dataset", (run_date,))
    }
    ai = conn.execute(
        """
        SELECT signal.*, news.title AS news_title, news.source AS news_source
        FROM ai_text_signals AS signal
        JOIN policy_news AS news
          ON news.id = signal.news_id
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
    db_status = _database_write_status(conn, run_date)
    prior_yields = _previous_values(conn, "bond_yields", "tenor", "yield_value", run_date)
    prior_funding = _previous_values(conn, "funding_rates", "rate_name", "rate_value", run_date)
    chart_paths = generate_report_charts(conn, run_date, output_dir)
    confidence = int(signal_details.get("confidence", 0))
    bias = signal_details.get("directional_bias", "均衡")
    conflicts = signal_details.get("conflicts", [])
    structure_notes = _market_structure_notes(futures, yields, funding, omo, prior_yields, prior_funding)

    raw_count = (
        len(futures) + len(yields) + len(funding) + len(omo) + len(news) + len(macro)
        + len(macro_history) + len(treasury_calendar) + len(curve_comparison)
    )
    lines = [
        f"# 中国国债期货每日真实数据监控报告 - {run_date}",
        "",
        "## 30秒执行摘要",
        f"- **结论：{_market_view_label(signal['market_view'])}，中性区间内{bias}**；综合评分 {signal['total_score']:.2f}，置信度 {confidence}/100。",
        f"- **当日变化：** {structure_notes[0][2:] if structure_notes else '核心数据无可用变化。'}",
        f"- **核心张力：** {conflicts[0] if conflicts else '有效方向信号未形成明显对冲。'}",
        f"- **下一日关注：** {_tomorrow_focus(treasury_calendar, collection_status)}",
        "- 置信度同时反映数据覆盖和多空信号一致性，不是胜率承诺。",
        "",
        "## 每日市场判断",
        f"- 市场观点：**{_market_view_label(signal['market_view'])}**",
        f"- 综合评分：**{signal['total_score']:.2f}**；置信度：**{confidence}/100**",
        "",
        "## 核心多周期面板",
        "| 指标 | 当前 | 1日变化 | 5日变化 | 20日分位 |",
        "|---|---:|---:|---:|---:|",
    ]
    lines.extend(_multi_horizon_rows(conn, run_date))
    lines.extend(["", "## 市场结构提示"])
    lines.extend(structure_notes)
    lines.extend([
        "",
        "## 核心驱动与冲突",
    "",
        "## 评分拆解",
        "| 维度 | 权重 | 分数 | 可用 | 判断依据 |",
        "|---|---:|---:|---|---|",
    ])
    lines.extend(
        f"| {item['category']} | {float(item.get('weight', 1)):.1f} | {float(item['score']):.2f} | "
        f"{'是' if item.get('available', True) else '否'} | {item['reason']} |"
        for item in score_items
    )
    if conflicts:
        lines.extend(["", "**信号冲突：**"] + [f"- {item}" for item in conflicts])

    lines.extend(["", "## 图表快照"])
    lines.extend(f"![{path.stem}](assets/{path.name})" for path in chart_paths)

    lines.extend(["", "## 期货量价与持仓", "| 合约 | 日收益 | 持仓1日变化 | 成交/20日 | 持仓/20日 | 四象限 |", "|---|---:|---:|---:|---:|---|"])
    lines.extend(_futures_position_rows(conn, run_date))

    lines.extend(["", "## 曲线结构", "| 结构 | 当前 | 1日变化 | 5日变化 |", "|---|---:|---:|---:|"])
    lines.extend(_curve_structure_rows(conn, run_date))

    lines.extend(["", "## 可交割券与基差", f"- {_status_sentence(collection_status, 'ctd_basis_irr')}"])

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

    lines.extend(["", "## 收益率曲线概览", "| 期限 | 收益率 | 较上一期 |", "|---|---:|---:|"])
    lines.extend(
        f"| {row['tenor']} | {row['yield_value']:.3f}% | "
        f"{_format_bp_change(row['yield_value'], prior_yields.get(row['tenor']))} |"
        for row in yields
    )

    lines.extend([
        "", "## 中债—CFETS 收益率曲线偏差监测",
        "| 期限 | 中债 | CFETS | CFETS − 中债 | 数据日 |",
        "|---|---:|---:|---:|---|",
    ])
    if curve_comparison:
        lines.extend(
            f"| {row['tenor']} | {row['chinabond_yield']:.4f}% | {row['cfets_yield']:.4f}% | "
            f"{row['deviation_bp']:+.2f} bp | {row['observation_date']} |"
            for row in curve_comparison
        )
    else:
        lines.append("| 无可比数据 | — | — | — | — |")
    lines.append("- 该偏差用于交叉核验发布与拟合口径，不进入每日方向评分，也不代表任一来源错误。")

    lines.extend(["", "## 资金面概览", "| 指标 | 利率 | 较上一期 |", "|---|---:|---:|"])
    lines.extend(
        f"| {row['rate_name']} | {row['rate_value']:.3f}% | "
        f"{_format_bp_change(row['rate_value'], prior_funding.get(row['rate_name']))} |"
        for row in funding
    )
    lines.append(f"- 同业存单/IRS分层：{_status_sentence(collection_status, 'funding_ncd_irs')}。")

    lines.extend(["", "## 宏观基本面概览", "| 指标 | 数值 | 数据期 |", "|---|---:|---|"])
    lines.extend(
        f"| {_macro_indicator_label(row['indicator'])} | {row['value']:.2f}{_macro_unit(row['indicator'])} | "
        f"{row['period']} |"
        for row in macro
    )
    lines.append("- 宏观指标按月度/不定期发布，记录的是运行日可得的最新一期数据。")

    lines.extend([
        "", "## 近6期国家统计局宏观趋势",
        "| 数据期 | CPI 同比 | PPI 同比 | 制造业 PMI |",
        "|---|---:|---:|---:|",
    ])
    lines.extend(_macro_history_table_rows(macro_history))
    lines.extend(_macro_momentum_notes(macro_history))
    lines.append("- 数据来自国家统计局数据发布页，并按日报运行日截断，避免使用事后发布信息。")

    lines.extend([
        "", "## 财政部国债发行日历",
        "| 招标日 | 期限 | 计划发行额 | 官方通知 |",
        "|---|---:|---:|---|",
    ])
    if treasury_calendar:
        lines.extend(
            f"| {row['auction_date']} | {row['tenor']} | {row['planned_amount']:.0f} 亿元 | "
            f"[{_escape_markdown(row['title'])}]({row['source_url']}) |"
            for row in treasury_calendar
        )
    else:
        status = collection_status.get("treasury_issuance_calendar", {})
        label = "经确认暂无已公告安排" if status.get("status") == "empty" else "数据源不可用，不代表无发行"
        lines.append(f"| {label} | — | — | — |")
    lines.append("- 展示运行日前财政部已发布、且招标日在运行日前3日至后14日内的记账式国债安排。")
    seven_day_amount = sum(float(row["planned_amount"]) for row in treasury_calendar[:])
    lines.append(f"- 当前可见窗口计划发行额：{seven_day_amount:.0f} 亿元；到期与净融资缺少同口径官方明细，不做差额估算。")
    lines.append(f"- 招标结果：{_status_sentence(collection_status, 'treasury_auction_results')}")

    lines.extend(
        [
            "",
            "## 公开市场操作概览",
            "| 类型 | 期限 | 投放 | 到期 | 净投放 | 来源标题 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    lines.extend(
        f"| {_operation_type_label(row['operation_type'])} | {_format_tenor(row['tenor_days'])} | "
        f"{row['operation_amount']:.0f} 亿元 | {row['maturity_amount']:.0f} 亿元 | "
        f"{row['net_injection_amount']:.0f} 亿元 | {row['source_title']} |"
        for row in omo
    )

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
                f"- 原始标题：{row['news_title']}",
                f"- 事件分类：{_event_type_label(row['event_type'])}",
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
    lines.extend(["", "## 跨市场核验", f"- {_status_sentence(collection_status, 'cross_market')}"])
    lines.extend(["", "## 历史信号检验（探索性）"])
    lines.extend(_historical_validation(conn, run_date))
    lines.extend([
        "",
        "## 附录：数据状态与新鲜度",
        "| 数据集 | 状态 | 行数 | 观测日 | 来源 | 说明 |",
        "|---|---|---:|---|---|---|",
    ])
    lines.extend(_collection_status_rows(collection_status))
    lines.extend([
        "",
        "## 附录：数据真实性检查",
        f"- 国债期货合约：{len(futures)} 条；收益率期限：{len(yields)} 条；资金利率：{len(funding)} 条。",
        f"- 公开市场操作：{len(omo)} 条；新闻：{len(news)} 条；宏观：{len(macro)} 条。",
        f"- 当日真实数据合计：{raw_count} 条。核心覆盖不足会直接失败。",
    ])
    lines.extend(
        [
            "",
            "## 数据库写入结果",
            f"- database: {db_status['database']}",
            f"- futures_quotes: {db_status['futures_quotes']} rows",
            f"- bond_yields: {db_status['bond_yields']} rows",
            f"- funding_rates: {db_status['funding_rates']} rows",
            f"- open_market_operations: {db_status['open_market_operations']} rows",
            f"- policy_news: {db_status['policy_news']} rows",
            f"- macro_indicators: {db_status['macro_indicators']} rows",
            f"- macro_history: {db_status['macro_history']} rows",
            f"- treasury_issuance_calendar: {db_status['treasury_issuance_calendar']} rows",
            f"- yield_curve_comparisons: {db_status['yield_curve_comparisons']} rows",
            f"- ai_text_signals: {db_status['ai_text_signals']} rows",
            f"- daily_features: {db_status['daily_features']} row",
            f"- daily_market_signals: {db_status['daily_market_signals']} row",
            f"- run_status: {db_status['run_status']}",
            "",
            "## 方法说明",
            "文本层用于把真实政策/新闻转成固定 schema 的利率债研究信号；规则评分用于解释当日数据含义，不直接预测价格。",
            "",
        ]
    )

    path = output_dir / f"{run_date}_daily_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _multi_horizon_rows(conn: sqlite3.Connection, run_date: str) -> list[str]:
    rows: list[str] = []
    yield_series = conn.execute(
        "SELECT date, yield_value AS value FROM bond_yields WHERE tenor='10Y' AND date<=? ORDER BY date DESC LIMIT 20",
        (run_date,),
    ).fetchall()[::-1]
    rows.append(_level_horizon_row("10Y国债收益率", yield_series, "%", bp=True))
    anchor_row = conn.execute(
        "SELECT rate_name FROM funding_rates WHERE date=? AND rate_name IN ('DR007','FDR007') ORDER BY rate_name LIMIT 1",
        (run_date,),
    ).fetchone()
    if anchor_row:
        anchor = str(anchor_row["rate_name"])
        series = conn.execute(
            "SELECT date, rate_value AS value FROM funding_rates WHERE rate_name=? AND date<=? ORDER BY date DESC LIMIT 20",
            (anchor, run_date),
        ).fetchall()[::-1]
        rows.append(_level_horizon_row(anchor, series, "%", bp=True))
    futures = conn.execute(
        "SELECT date, AVG(daily_return) AS value FROM futures_quotes WHERE date<=? GROUP BY date ORDER BY date DESC LIMIT 20",
        (run_date,),
    ).fetchall()[::-1]
    if futures:
        values = [float(row["value"]) for row in futures]
        five = _compound(values[-5:])
        rows.append(f"| 期货平均收益 | {values[-1]:+.3%} | {values[-1]:+.3%} | {five:+.3%} | {_pct_rank(values):.0%} |")
    activity = conn.execute(
        "SELECT date, SUM(volume) AS volume, SUM(open_interest) AS oi FROM futures_quotes WHERE date<=? GROUP BY date ORDER BY date DESC LIMIT 20",
        (run_date,),
    ).fetchall()[::-1]
    if len(activity) >= 2:
        volumes = [float(row["volume"]) for row in activity]
        oi = [float(row["oi"]) for row in activity]
        rows.append(f"| 总成交量 | {volumes[-1]:,.0f} | {volumes[-1]/volumes[-2]-1:+.1%} | — | {_pct_rank(volumes):.0%} |")
        five_oi = f"{oi[-1]/oi[-6]-1:+.1%}" if len(oi) >= 6 else "—"
        rows.append(
            f"| 总持仓量 | {oi[-1]:,.0f} | {oi[-1]/oi[-2]-1:+.1%} | {five_oi} | {_pct_rank(oi):.0%} |"
        )
    return rows or ["| 数据不足 | — | — | — | — |"]


def _level_horizon_row(label: str, series, unit: str, bp: bool = False) -> str:
    if not series:
        return f"| {label} | — | — | — | — |"
    values = [float(row["value"]) for row in series]
    one = values[-1] - values[-2] if len(values) >= 2 else None
    five = values[-1] - values[-6] if len(values) >= 6 else None
    scale, suffix = (100, " bp") if bp else (1, unit)
    return (
        f"| {label} | {values[-1]:.3f}{unit} | "
        f"{one*scale:+.1f}{suffix if one is not None else ''}" if one is not None else f"| {label} | {values[-1]:.3f}{unit} | —"
    ) + (f" | {five*scale:+.1f}{suffix} |" if five is not None else " | — |") + f" {_pct_rank(values):.0%} |"


def _futures_position_rows(conn: sqlite3.Connection, run_date: str) -> list[str]:
    result = []
    contracts = [row["contract"] for row in conn.execute("SELECT contract FROM futures_quotes WHERE date=? ORDER BY contract", (run_date,))]
    for contract in contracts:
        history = conn.execute(
            "SELECT daily_return, volume, open_interest FROM futures_quotes WHERE contract=? AND date<=? ORDER BY date DESC LIMIT 20",
            (contract, run_date),
        ).fetchall()[::-1]
        current = history[-1]
        prior = history[-2] if len(history) >= 2 else None
        baseline = history[:-1] or history
        avg_volume = sum(float(row["volume"]) for row in baseline) / len(baseline)
        avg_oi = sum(float(row["open_interest"]) for row in baseline) / len(baseline)
        ret = float(current["daily_return"])
        oi_change = float(current["open_interest"]) / float(prior["open_interest"]) - 1 if prior else None
        quadrant = _quadrant(ret, oi_change)
        result.append(
            f"| {contract} | {ret:+.3%} | {_pct(oi_change)} | {float(current['volume'])/avg_volume:.2f}x | "
            f"{float(current['open_interest'])/avg_oi:.2f}x | {quadrant} |"
        )
    return result or ["| 无 | — | — | — | — | 数据不足 |"]


def _curve_structure_rows(conn: sqlite3.Connection, run_date: str) -> list[str]:
    dates = [row["date"] for row in conn.execute(
        "SELECT DISTINCT date FROM bond_yields WHERE date<=? ORDER BY date DESC LIMIT 6", (run_date,)
    )]
    maps = []
    for value_date in dates:
        maps.append({row["tenor"]: float(row["yield_value"]) for row in conn.execute("SELECT tenor,yield_value FROM bond_yields WHERE date=?", (value_date,))})
    definitions = {
        "2s10s": lambda curve: curve.get("10Y") - curve.get("2Y") if "10Y" in curve and "2Y" in curve else None,
        "10s30s": lambda curve: curve.get("30Y") - curve.get("10Y") if "30Y" in curve and "10Y" in curve else None,
        "2s5s10s蝶式": lambda curve: curve.get("2Y") - 2 * curve.get("5Y") + curve.get("10Y") if all(key in curve for key in ("2Y", "5Y", "10Y")) else None,
    }
    result = []
    for label, fn in definitions.items():
        values = [fn(curve) for curve in maps]
        current = values[0] if values else None
        one = current - values[1] if current is not None and len(values) > 1 and values[1] is not None else None
        five = current - values[5] if current is not None and len(values) > 5 and values[5] is not None else None
        result.append(f"| {label} | {_bp(current)} | {_bp(one)} | {_bp(five)} |")
    return result


def _macro_momentum_notes(rows) -> list[str]:
    by_indicator: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        by_indicator.setdefault(str(row["indicator"]), []).append((str(row["period"]), float(row["value"])))
    notes = []
    labels = {"CPI_YOY": "CPI", "PPI_YOY": "PPI", "PMI_MFG": "制造业PMI"}
    for indicator, values in by_indicator.items():
        ordered = sorted(values, reverse=True)
        if len(ordered) < 2:
            continue
        direction = "改善" if ordered[0][1] > ordered[1][1] else "走弱" if ordered[0][1] < ordered[1][1] else "持平"
        extra = f"，距50为 {ordered[0][1]-50:+.1f}" if indicator == "PMI_MFG" else ""
        notes.append(f"- {labels.get(indicator, indicator)} 较前值{direction} {ordered[0][1]-ordered[1][1]:+.1f}{extra}。")
    return notes


def _historical_validation(conn: sqlite3.Connection, run_date: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT q.date, AVG(q.daily_return) AS ret, s.total_score
        FROM futures_quotes q LEFT JOIN daily_market_signals s ON s.date=q.date
        WHERE q.date<=? GROUP BY q.date ORDER BY q.date
        """,
        (run_date,),
    ).fetchall()
    observations = []
    for index, row in enumerate(rows):
        score = row["total_score"]
        if score in (None, 0) or index + 1 >= len(rows):
            continue
        direction = 1 if float(score) > 0 else -1
        next_1d = float(rows[index + 1]["ret"])
        next_5d = _compound([float(item["ret"]) for item in rows[index + 1:index + 6]]) if index + 5 < len(rows) else None
        observations.append((direction * next_1d > 0, direction * next_5d > 0 if next_5d is not None else None))
    if not observations:
        return ["- 样本不足，暂无法计算。"]
    hits_1d = sum(item[0] for item in observations) / len(observations)
    valid_5d = [item[1] for item in observations if item[1] is not None]
    text = f"- 历史非中性信号 {len(observations)} 个，次日方向命中率 {hits_1d:.1%}"
    if valid_5d:
        text += f"，5日方向命中率 {sum(valid_5d)/len(valid_5d):.1%}（n={len(valid_5d)}）"
    return [text + "。", "- 该检验未扣除交易成本，也未做样本外验证，只用于监测规则是否失效。"]


def _collection_status_rows(statuses: dict) -> list[str]:
    labels = {"ok": "正常", "partial": "部分", "empty": "经确认无记录", "unavailable": "不可用"}
    return [
        f"| {key} | {labels.get(value.get('status'), value.get('status', '未知'))} | {value.get('row_count', 0)} | "
        f"{value.get('observation_date') or '—'} | {_escape_markdown(value.get('data_source', '—'))} | {_escape_markdown(value.get('message', ''))} |"
        for key, value in statuses.items()
    ] or ["| 无状态记录 | 未知 | 0 | — | — | 旧数据库尚未记录采集状态 |"]


def _status_sentence(statuses: dict, dataset: str) -> str:
    status = statuses.get(dataset)
    if not status:
        return "未记录数据状态"
    labels = {"ok": "正常", "partial": "部分可用", "empty": "经确认无记录", "unavailable": "不可用"}
    return f"{labels.get(status['status'], status['status'])}：{status['message']}"


def _tomorrow_focus(calendar, statuses: dict) -> str:
    if calendar:
        nearest = calendar[0]
        return f"关注 {nearest['auction_date']} {nearest['tenor']} 国债招标（{nearest['planned_amount']:.0f}亿元）及资金利率分层。"
    return f"资金利率分层与长端持仓变化；发行日历{_status_sentence(statuses, 'treasury_issuance_calendar')}。"


def _compound(values: list[float]) -> float:
    result = 1.0
    for value in values:
        result *= 1 + value
    return result - 1


def _pct_rank(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(value <= values[-1] for value in values) / len(values)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2%}"


def _bp(value: float | None) -> str:
    return "—" if value is None else f"{value*100:+.1f} bp"


def _quadrant(ret: float, oi_change: float | None) -> str:
    if oi_change is None:
        return "数据不足"
    return ("价涨" if ret >= 0 else "价跌") + ("增仓" if oi_change >= 0 else "减仓")


def _database_write_status(conn: sqlite3.Connection, run_date: str) -> dict[str, object]:
    db_row = conn.execute("PRAGMA database_list").fetchone()
    db_path = db_row["file"] if db_row and db_row["file"] else "data/bond_futures_monitor.db"
    try:
        db_path = str(Path(db_path).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        db_path = str(db_path)
    db_path = db_path.replace("\\", "/")
    tables = [
        "futures_quotes",
        "bond_yields",
        "funding_rates",
        "open_market_operations",
        "policy_news",
        "macro_indicators",
        "macro_history",
        "treasury_issuance_calendar",
        "yield_curve_comparisons",
        "ai_text_signals",
        "daily_features",
        "daily_market_signals",
    ]
    result: dict[str, object] = {"database": db_path}
    for table in tables:
        result[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE date = ?", (run_date,)).fetchone()["n"]
    run_log = conn.execute(
        "SELECT status FROM run_log WHERE run_date = ? ORDER BY id DESC LIMIT 1",
        (run_date,),
    ).fetchone()
    result["run_status"] = run_log["status"] if run_log else "unknown"
    return result


def _macro_history_table_rows(rows) -> list[str]:
    by_period: dict[str, dict[str, float]] = {}
    for row in rows:
        by_period.setdefault(str(row["period"]), {})[str(row["indicator"])] = float(row["value"])
    result = []
    for period in sorted(by_period, reverse=True)[:6]:
        values = by_period[period]
        result.append(
            f"| {period} | {_format_macro_history(values.get('CPI_YOY'), '%')} | "
            f"{_format_macro_history(values.get('PPI_YOY'), '%')} | "
            f"{_format_macro_history(values.get('PMI_MFG'), '')} |"
        )
    return result or ["| 暂无官方历史数据 | — | — | — |"]


def _format_macro_history(value: float | None, unit: str) -> str:
    return "—" if value is None else f"{value:.1f}{unit}"


def _escape_markdown(value: str) -> str:
    return str(value).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


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


def _operation_type_label(value: str) -> str:
    return {
        "reverse_repo": "逆回购",
        "outright_reverse_repo": "买断式逆回购",
    }.get(value, value)


def _macro_indicator_label(value: str) -> str:
    return {
        "LPR_1Y": "LPR 1年期",
        "LPR_5Y": "LPR 5年期以上",
        "CPI_YOY": "CPI 同比",
        "PPI_YOY": "PPI 同比",
        "PMI_MFG": "制造业 PMI",
    }.get(value, value)


def _macro_unit(value: str) -> str:
    return "" if value == "PMI_MFG" else "%"


def _format_tenor(value) -> str:
    if value is None:
        return "缺失"
    return f"{int(value)} 天"


def _previous_values(
    conn: sqlite3.Connection,
    table: str,
    key_column: str,
    value_column: str,
    run_date: str,
) -> dict[str, float]:
    allowed = {
        ("bond_yields", "tenor", "yield_value"),
        ("funding_rates", "rate_name", "rate_value"),
    }
    if (table, key_column, value_column) not in allowed:
        raise ValueError(f"Unsupported previous-value query: {table}.{key_column}.{value_column}")
    prior = conn.execute(f"SELECT MAX(date) AS d FROM {table} WHERE date < ?", (run_date,)).fetchone()
    if not prior or not prior["d"]:
        return {}
    return {
        str(row[key_column]): float(row[value_column])
        for row in conn.execute(
            f"SELECT {key_column}, {value_column} FROM {table} WHERE date = ?",
            (prior["d"],),
        )
    }


def _format_bp_change(current: float, previous: float | None) -> str:
    if previous is None:
        return "缺失"
    return f"{(float(current) - float(previous)) * 100:+.1f} bp"


def _market_structure_notes(futures, yields, funding, omo, prior_yields, prior_funding) -> list[str]:
    notes: list[str] = []
    yield_map = {row["tenor"]: float(row["yield_value"]) for row in yields}
    funding_map = {row["rate_name"]: float(row["rate_value"]) for row in funding}

    if futures:
        strongest = max(futures, key=lambda row: float(row["daily_return"]))
        weakest = min(futures, key=lambda row: float(row["daily_return"]))
        notes.append(
            f"- 期货强弱：{strongest['contract']} 表现最强（{strongest['daily_return']:+.3%}），"
            f"{weakest['contract']} 表现最弱（{weakest['daily_return']:+.3%}）。"
        )
    if "10Y" in yield_map:
        change = _format_bp_change(yield_map["10Y"], prior_yields.get("10Y"))
        curve = ""
        if "2Y" in yield_map and "30Y" in yield_map:
            curve = (
                f"；10Y-2Y 为 {(yield_map['10Y'] - yield_map['2Y']) * 100:.1f} bp，"
                f"30Y-10Y 为 {(yield_map['30Y'] - yield_map['10Y']) * 100:.1f} bp"
            )
        notes.append(f"- 利率曲线：10Y 收益率 {yield_map['10Y']:.3f}%，较上一期 {change}{curve}。")

    anchor = "DR007" if "DR007" in funding_map else "FDR007" if "FDR007" in funding_map else None
    broad = "R007" if "R007" in funding_map else "FR007" if "FR007" in funding_map else None
    if anchor:
        change = _format_bp_change(funding_map[anchor], prior_funding.get(anchor))
        spread = (
            f"，{broad}-{anchor} 利差 {(funding_map[broad] - funding_map[anchor]) * 100:+.1f} bp"
            if broad else ""
        )
        notes.append(f"- 资金锚：{anchor} 为 {funding_map[anchor]:.3f}%，较上一期 {change}{spread}。")

    if omo:
        net = sum(float(row["net_injection_amount"]) for row in omo)
        rates = [float(row["operation_rate"]) for row in omo if row["operation_rate"] is not None]
        rate_text = f"，操作利率 {rates[-1]:.2f}%" if rates else ""
        notes.append(f"- 公开市场：当日合计净投放 {net:+.0f} 亿元{rate_text}。")
    else:
        notes.append("- 公开市场：未取得可完整计算净投放的记录，本项保持中性。")
    return notes


def _feature_panel_rows(feature_groups: dict) -> list[str]:
    labels = {
        "yield_10y_change": "10Y 收益率变化",
        "yield_30y_change": "30Y 收益率变化",
        "spread_10y_2y": "10Y-2Y 利差",
        "spread_30y_10y": "30Y-10Y 利差",
        "funding_anchor_name": "资金锚名称",
        "funding_anchor_value": "资金锚水平",
        "funding_anchor_change": "资金锚变化",
        "repo_7d_spread": "7天回购分层利差",
        "shibor_7d_spread": "Shibor 7D-资金锚",
        "available_rates": "可用资金利率",
        "omo_net_injection_amount": "公开市场净投放",
        "omo_operation_rate": "公开市场操作利率",
        "operation_count": "公开市场操作记录数",
        "avg_futures_return": "期货平均日收益率",
        "avg_volume_change": "成交活跃度变化",
        "contract_count": "覆盖合约数量",
        "avg_ai_sentiment_score": "文本情绪均值",
        "signal_count": "文本信号数量",
        "lpr_1y": "LPR 1年期",
        "lpr_5y": "LPR 5年期以上",
        "cpi_yoy": "CPI 同比",
        "ppi_yoy": "PPI 同比",
        "pmi_mfg": "制造业 PMI",
        "indicator_count": "宏观指标数量",
    }
    group_labels = {
        "rates": "利率",
        "funding": "资金面",
        "open_market_operations": "公开市场操作",
        "futures": "期货量价",
        "text": "文本",
        "macro": "宏观基本面",
    }
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
        "open_market_operations": "公开市场操作",
        "policy_news": "政策/新闻",
        "macro": "宏观基本面",
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

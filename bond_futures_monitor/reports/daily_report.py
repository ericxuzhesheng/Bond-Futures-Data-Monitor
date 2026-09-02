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

    signal_details = json.loads(signal["details_json"])
    score_items = signal_details.get("score_items", [])
    feature_details = signal_details.get("feature_snapshot", {}).get("details", {})
    db_status = _database_write_status(conn, run_date)
    prior_yields = _previous_values(conn, "bond_yields", "tenor", "yield_value", run_date)
    prior_funding = _previous_values(conn, "funding_rates", "rate_name", "rate_value", run_date)
    chart_paths = generate_report_charts(conn, run_date, output_dir)
    futures = sorted(futures, key=lambda row: ("TS", "TF", "T", "TL").index(row["contract"]))
    yields = sorted(yields, key=lambda row: float(row["tenor"].rstrip("Y")))
    view = _market_view_label(signal["market_view"])
    bias = signal_details.get("directional_bias", "均衡")
    verdict = f"中性偏{bias[-1]}" if signal["market_view"] == "neutral" and bias in ("偏多", "偏空") else view
    confidence = signal_details.get("confidence")
    confidence_text = f"{confidence}/100" if confidence is not None else "未记录"
    raw_count = sum(len(rows) for rows in (
        futures, yields, funding, omo, news, macro, macro_history, treasury_calendar, curve_comparison
    ))

    lines = [
        "# 国债期货日报",
        "",
        f"**{run_date}** · 收盘观察 · {verdict}",
        "",
        "> 基于当日已入库行情与公开数据整理。宏观指标采用当时已发布的数据期。",
        "",
        "## 当日简评",
        "",
    ]
    rebuilt = conn.execute(
        "SELECT 1 FROM run_log WHERE run_date=? AND status='success' AND message LIKE 'Historical rebuild%' LIMIT 1",
        (run_date,),
    ).fetchone()
    if rebuilt:
        lines[-2:-2] = ["> 历史重建版：使用当前规则重算，不代表当日实际发布的判断。", ""]
    lines.extend(_editorial_summary(futures, yields, funding, omo, prior_yields, prior_funding, signal, score_items))
    lines.extend([
        "",
        f"模型评分 **{signal['total_score']:+.2f}** · 规则置信指标 **{confidence_text}**",
        "",
        "这个指标反映评分输入的覆盖程度和方向一致性，不能解读为上涨概率。",
        "",
        "### 关键数字",
        "",
        "| 指标 | 当前 | 1日变化 | 5日变化 | 近20次观测分位 |",
        "|---|---:|---:|---:|---:|",
    ])
    lines.extend(_multi_horizon_rows(conn, run_date))
    lines.extend([
        "",
        "*收益率与资金利率的变化以 bp 计，1 bp 等于 0.01 个百分点。分位只使用已有同口径观测，"
        "不足20条时按实际样本计算；缺失比较标为“缺失”。期货5日栏为五次观测的复合收益。*",
        "",
        "## 期货表现",
        "",
        _chart_embed(chart_paths[0], "国债期货累计表现"),
        "",
        "*以窗口首个观测日前的100为基准，逐日复合各品种收益率；横轴列出观测日期。*",
        "",
        "| 合约 | 日收益 | 持仓变化 | 成交量/均值 | 持仓量/均值 | 量价状态 |",
        "|---|---:|---:|---:|---:|---|",
    ])
    lines.extend(_futures_position_rows(conn, run_date))
    lines.extend([
        "",
        "*均值取当前20次观测窗口内、当日之前的数据。量价状态只描述价格与持仓的同日变化，"
        "不据此判断多空开仓。TS、TF、T、TL 分别对应2年、5年、10年和30年期国债期货品种。*",
        "",
        "<details>",
        "<summary>查看期货收盘价和成交持仓明细</summary>",
        "",
        "| 合约 | 收盘价 | 日收益率 | 成交量 | 持仓量 |",
        "|---|---:|---:|---:|---:|",
    ])
    lines.extend(
        f"| {row['contract']} | {row['close_price']:.3f} | {row['daily_return']:.4%} | "
        f"{row['volume']:,.0f} | {row['open_interest']:,.0f} |" for row in futures
    )
    lines.extend(["", "</details>", "", "## 利率与资金", "", "### 国债收益率曲线", "",
                  _chart_embed(chart_paths[1], "当日与前一观测日国债收益率曲线"), "",
                  "| 结构 | 当前 | 1日变化 | 5日变化 |", "|---|---:|---:|---:|"])
    lines.extend(_curve_structure_rows(conn, run_date))
    lines.extend([
        "",
        "*图中期限按类别等距排列。2s10s 为10年减2年收益率，10s30s 为30年减10年收益率。"
        "蝶式采用2年减两倍5年再加10年收益率，均以 bp 表示。*",
        "",
        "<details>",
        "<summary>查看各期限收益率与中债、CFETS 核验</summary>",
        "",
        "| 期限 | 收益率 | 较上一观测日 |",
        "|---|---:|---:|",
    ])
    if any("interpolated_1y_3y" in row["data_source"] for row in yields):
        lines[-2:-2] = [
            "*本日采用中债备用曲线；2年期由1年与3年线性插值，并非直接发布值。涉及2年期的利差与蝶式也含插值成分。*",
            "",
        ]
    lines.extend(
        f"| {row['tenor']} | {row['yield_value']:.3f}% | "
        f"{_format_bp_change(row['yield_value'], prior_yields.get(row['tenor']))} |" for row in yields
    )
    if curve_comparison:
        lines.extend(["", "| 期限 | 中债 | CFETS | CFETS − 中债 | 数据日 |",
                      "|---|---:|---:|---:|---|"])
        lines.extend(
            f"| {row['tenor']} | {row['chinabond_yield']:.4f}% | {row['cfets_yield']:.4f}% | "
            f"{row['deviation_bp']:+.2f} bp | {row['observation_date']} |" for row in curve_comparison
        )
        lines.extend(["", "两条曲线的偏差用于核对发布与拟合口径，不计入方向评分。"])
    else:
        lines.extend(["", "本期缺少两家发布方的可比曲线。"])
    lines.extend(["", "</details>", "", "### 资金利率", "",
                  _chart_embed(chart_paths[2], "资金利率历史观测"), "",
                  "| 指标 | 利率 | 较上一观测日 |", "|---|---:|---:|"])
    lines.extend(
        f"| {row['rate_name']} | {row['rate_value']:.3f}% | "
        f"{_format_bp_change(row['rate_value'], prior_funding.get(row['rate_name']))} |" for row in funding
    )
    lines.extend(["", "*FDR 与 FR 是定盘利率，与 DR、R 加权成交利率口径不同。*", "",
                  "### 公开市场操作", ""])
    if omo:
        lines.extend(["金额单位为亿元。", "",
                      "| 类型 | 期限 | 投放 | 到期 | 净投放 |", "|---|---:|---:|---:|---:|"])
        lines.extend(
            f"| {_operation_type_label(row['operation_type'])} | {_format_tenor(row['tenor_days'])} | "
            f"{row['operation_amount']:,.0f} | {row['maturity_amount']:,.0f} | "
            f"{row['net_injection_amount']:+,.0f} |" for row in omo
        )
        lines.extend(["", "净投放为负数时表示净回笼。"])
    else:
        lines.append("本期没有取得可完整计算净投放的数据。")

    lines.extend(["", "## 宏观与后续观察", ""])
    lines.extend(_macro_momentum_notes(macro_history))
    lines.extend(["", _chart_embed(chart_paths[3], "CPI、PPI 与制造业 PMI 历史"), "",
                  "<details>", "<summary>查看宏观数据期与历史明细</summary>", "",
                  "| 指标 | 数值 | 数据期 |", "|---|---:|---|"])
    lines.extend(
        f"| {_macro_indicator_label(row['indicator'])} | {row['value']:.2f}{_macro_unit(row['indicator'])} | "
        f"{row['period']} |" for row in macro
    )
    lines.extend(["", "| 数据期 | CPI 同比 | PPI 同比 | 制造业 PMI |", "|---|---:|---:|---:|"])
    lines.extend(_macro_history_table_rows(macro_history))
    lines.extend(["", "国家统计局历史数据按日报日期截断，缺项保持缺失。", "", "</details>", ""])
    if treasury_calendar:
        lines.extend(["### 已公告国债招标", "", "| 招标日 | 期限 | 计划发行额 | 官方通知 |",
                      "|---|---|---:|---|"])
        lines.extend(
            f"| {row['auction_date']} | {row['tenor']} | {row['planned_amount']:.0f} 亿元 | "
            f"[{_escape_markdown(row['title'])}]({row['source_url']}) |" for row in treasury_calendar
        )
    else:
        calendar_state = collection_status.get("treasury_issuance_calendar", {}).get("status")
        lines.append("查询窗口内未发现已公告的国债招标安排。" if calendar_state == "empty"
                     else "本期未取得完整国债发行日历，发行规模和净融资暂不列数。")
    lines.extend(["", "下一次更新继续观察资金利率、长端收益率和期货持仓是否同向变化。"
                  "发行日历恢复后，再补充已公告招标安排。"])

    directional_ai = [row for row in ai if not (
        row["event_type"] == "other" and row["bond_impact"] == "neutral" and int(row["confidence"]) <= 2
    )]
    if directional_ai:
        lines.extend(["", "### 政策与新闻", ""])
        for row in directional_ai:
            contracts = ", ".join(json.loads(row["related_contracts"])) or "未指明"
            lines.extend([
                f"**{_escape_markdown(row['news_title'])}**",
                "",
                str(row["summary"]),
                "",
                f"{_event_type_label(row['event_type'])} · {_impact_label(row['bond_impact'])} · "
                f"{_maturity_label(row['affected_maturity'])} · 相关合约 {contracts} · 文本置信指标 {row['confidence']}/5",
                "",
                str(row["reasoning"]),
                "",
            ])

    lines.extend(["", "---", "", "## 方法与数据附录", "",
                  "本报告用于整理当日市场信息。评分阈值为 +2 和 -2，区间内保留中性判断。"
                  "缺少新闻、发行日历等输入时，相关解释范围也会收窄。", "",
                  "<details>", "<summary>展开评分依据与历史检验</summary>", "",
                  "| 维度 | 权重 | 分数 | 数据状态 | 判断依据 |", "|---|---:|---:|---|---|"])
    lines.extend(
        f"| {item['category']} | {float(item.get('weight', 1)):.1f} | {float(item['score']):+.2f} | "
        f"{'可用' if item.get('available', True) else '缺失'} | {item['reason']} |" for item in score_items
    )
    if signal_details.get("conflicts"):
        lines.extend([""] + signal_details["conflicts"])
    lines.extend(["", "### 风险边界", ""])
    for note in json.loads(signal["risk_notes"]):
        if "不是价格预测" in note:
            note = "规则评分用于研究观察，不提供价格预测或个性化交易建议。"
        lines.append(f"- {note}")
    lines.extend(["", "### 历史方向检验", ""])
    lines.extend(_historical_validation(conn, run_date))
    lines.extend(["", "这里按评分正负划分方向，包含尚未达到 ±2 阈值的记录。"
                  "历史评分受数据覆盖和规则版本影响，不等同于当时实际发布的判断。", "",
                  "### 原始特征", "", "| 分组 | 指标 | 数值 |", "|---|---|---:|"])
    lines.extend(_feature_panel_rows(feature_details.get("feature_groups", {})))
    lines.extend(["", "</details>", "", "<details>", "<summary>展开数据来源、缺项与运行记录</summary>", "",
                  f"本期共记录 {raw_count} 条数据，其中期货 {len(futures)} 条、收益率 {len(yields)} 条、"
                  f"资金利率 {len(funding)} 条。运行状态为 {db_status['run_status']}。", "",
                  "### 数据来源", "", "| 数据类别 | 来源 |", "|---|---|"])
    lines.extend(_data_source_rows(feature_details.get("data_sources", {})))
    if omo:
        lines.extend(["", "公开市场操作采用以下原始记录。", ""])
        lines.extend(f"- {_escape_markdown(row['source_title'])}" for row in omo)
    lines.extend(["", "### 数据状态", ""])
    for dataset, status in collection_status.items():
        label = DATASET_LABELS.get(dataset, dataset)
        state = {"ok": "正常", "partial": "部分可用", "empty": "无返回记录",
                 "unavailable": "不可用"}.get(status.get("status"), "未知")
        lines.extend([
            f"**{label} · {state}**",
            "",
            f"观测日 {status.get('observation_date') or '未记录'}，共 {status.get('row_count', 0)} 条。",
            "",
            f"`{dataset}`",
            "",
            # Raw diagnostic messages remain code, separate from reader-facing prose.
            "```text",
            str(status.get("message", "")).replace("```", "'''"),
            "```",
            "",
        ])
    lines.extend(["### 运行记录", "", "```text"])
    lines.extend(f"{key}: {value}" for key, value in db_status.items())
    lines.extend(["```", "", "</details>", ""])

    # Missing table cells use a readable word, not a typographic dash.
    content = "\n".join(lines).replace("—", "缺失")
    path = output_dir / f"{run_date}_daily_report.md"
    path.write_text(content, encoding="utf-8")
    return path


DATASET_LABELS = {
    "futures_quotes": "国债期货", "bond_yields": "国债收益率", "funding_rates": "资金利率",
    "open_market_operations": "公开市场操作", "macro_indicators": "最新宏观指标",
    "macro_history": "国家统计局历史", "yield_curve_comparisons": "双源曲线核验",
    "policy_news": "政策新闻", "treasury_issuance_calendar": "国债发行日历",
    "ctd_basis_irr": "可交割券、基差与 IRR", "treasury_auction_results": "国债招标结果",
    "cross_market": "跨市场数据", "funding_ncd_irs": "同业存单与 IRS",
}


def _chart_embed(path: Path, label: str) -> str:
    return f"![{label}](assets/{path.name})"


def _editorial_summary(futures, yields, funding, omo, prior_yields, prior_funding, signal, score_items):
    paragraphs = []
    if futures:
        strongest = max(futures, key=lambda row: float(row["daily_return"]))
        weakest = min(futures, key=lambda row: float(row["daily_return"]))
        all_up = all(row["daily_return"] > 0 for row in futures)
        all_down = all(row["daily_return"] < 0 for row in futures)
        opening = "国债期货各品种收涨" if all_up else "国债期货各品种收跌" if all_down else "国债期货表现分化"
        paragraphs.append(
            f"{opening}。{strongest['contract']} 表现相对最强，日收益 {strongest['daily_return']:+.3%}；"
            f"{weakest['contract']} 为 {weakest['daily_return']:+.3%}。"
        )
    yield_map = {row["tenor"]: float(row["yield_value"]) for row in yields}
    funding_map = {row["rate_name"]: float(row["rate_value"]) for row in funding}
    sentence = []
    if "10Y" in yield_map:
        sentence.append(f"10年国债收益率为 {yield_map['10Y']:.3f}%"
                        f"，较上一观测日变化 {_format_bp_change(yield_map['10Y'], prior_yields.get('10Y'))}。")
    anchor = next((name for name in ("FDR007", "DR007") if name in funding_map), None)
    if anchor:
        sentence.append(f"{anchor} 为 {funding_map[anchor]:.3f}%"
                        f"，变化 {_format_bp_change(funding_map[anchor], prior_funding.get(anchor))}。")
    if omo:
        net = sum(float(row["net_injection_amount"]) for row in omo)
        action = "净回笼" if net < 0 else "净投放"
        sentence.append(f"央行公开市场当日{action} {abs(net):,.0f} 亿元。")
    if sentence:
        paragraphs.append("".join(sentence))
    directional_items = [item for item in score_items if item["score"] != 0]
    reasons = [str(item["reason"]) for item in directional_items]
    if len(directional_items) == 1:
        item = directional_items[0]
        direction = "偏多" if item["score"] > 0 else "偏空"
        paragraphs.append(f"{item['category']}是本期唯一产生方向性得分的维度，贡献{direction}分值。"
                          "其余可用维度未触发方向性阈值，缺失的文本信号不参与计分。"
                          if not any(entry['category'] == '文本信号' and entry.get('available', True) for entry in score_items)
                          else f"{item['category']}是本期唯一产生方向性得分的维度，贡献{direction}分值。")
    elif reasons:
        paragraphs.append("模型中的方向性得分来自以下判断。" + "".join(reasons))
    else:
        paragraphs.append("各项输入均未触发方向性得分，模型保留中性判断。")
    return [line for paragraph in paragraphs for line in (paragraph, "")]


def _multi_horizon_rows(conn: sqlite3.Connection, run_date: str) -> list[str]:
    rows: list[str] = []
    yield_series = conn.execute(
        "SELECT date, yield_value AS value FROM bond_yields WHERE tenor='10Y' AND date<=? ORDER BY date DESC LIMIT 20",
        (run_date,),
    ).fetchall()[::-1]
    rows.append(_level_horizon_row("10Y国债收益率", yield_series, "%", bp=True))
    anchor_row = conn.execute(
        "SELECT rate_name FROM funding_rates WHERE date=? AND rate_name IN ('DR007','FDR007') ORDER BY rate_name DESC LIMIT 1",
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
        five = f"{_compound(values[-5:]):+.3%}" if len(values) >= 5 else "缺失"
        rows.append(f"| 期货平均收益 | {values[-1]:+.3%} | {values[-1]:+.3%} | {five} | {_pct_rank(values):.0%} |")
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
    contracts.sort(key=lambda contract: ("TS", "TF", "T", "TL").index(contract))
    for contract in contracts:
        history = conn.execute(
            "SELECT daily_return, volume, open_interest FROM futures_quotes WHERE contract=? AND date<=? ORDER BY date DESC LIMIT 20",
            (contract, run_date),
        ).fetchall()[::-1]
        current = history[-1]
        prior = history[-2] if len(history) >= 2 else None
        baseline = history[:-1]
        avg_volume = sum(float(row["volume"]) for row in baseline) / len(baseline) if baseline else 0
        avg_oi = sum(float(row["open_interest"]) for row in baseline) / len(baseline) if baseline else 0
        ret = float(current["daily_return"])
        oi_change = float(current["open_interest"]) / float(prior["open_interest"]) - 1 if prior and prior["open_interest"] > 0 else None
        quadrant = _quadrant(ret, oi_change)
        volume_ratio = f"{float(current['volume'])/avg_volume:.2f}x" if avg_volume > 0 else "缺失"
        oi_ratio = f"{float(current['open_interest'])/avg_oi:.2f}x" if avg_oi > 0 else "缺失"
        result.append(
            f"| {contract} | {ret:+.3%} | {_pct(oi_change)} | {volume_ratio} | {oi_ratio} | {quadrant} |"
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
        delta = ordered[0][1] - ordered[1][1]
        change = f"较前期{'上升' if delta > 0 else '下降'} {abs(delta):.1f}" if delta else "与前期持平"
        unit = "" if indicator == "PMI_MFG" else "%"
        extra = ""
        if indicator == "PMI_MFG":
            distance = ordered[0][1] - 50
            extra = f"，{'高于' if distance >= 0 else '低于'}50荣枯线 {abs(distance):.1f}"
        notes.append(f"{ordered[0][0]} 的 {labels.get(indicator, indicator)} 为 {ordered[0][1]:.1f}{unit}，{change}{extra}。\n")
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
    text = f"- 历史非零评分记录 {len(observations)} 个，次日方向命中率 {hits_1d:.1%}"
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

    anchor = "FDR007" if "FDR007" in funding_map else "DR007" if "DR007" in funding_map else None
    broad = "FR007" if anchor == "FDR007" else "R007"
    if broad not in funding_map:
        broad = None
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
        rows.append(f"| {labels.get(key, key)} | `{source}` |" if source else f"| {labels.get(key, key)} | 无 |")
    return rows or ["| 无 | 无 |"]


def _format_feature_value(value) -> str:
    if value is None:
        return "缺失"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "无"
    return str(value)

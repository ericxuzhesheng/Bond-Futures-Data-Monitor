"""Small dependency-free SVG charts for the Markdown daily report."""

from __future__ import annotations

import html
import sqlite3
from collections import defaultdict
from pathlib import Path


COLORS = ["#245b85", "#b58b3b", "#75804b", "#a7657b", "#64748b"]


def generate_report_charts(conn: sqlite3.Connection, run_date: str, output_dir: Path) -> list[Path]:
    asset_dir = output_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        _futures_chart(conn, run_date, asset_dir),
        _curve_chart(conn, run_date, asset_dir),
        _funding_chart(conn, run_date, asset_dir),
        _macro_chart(conn, run_date, asset_dir),
    ]
    return paths


def _futures_chart(conn, run_date, asset_dir):
    rows = conn.execute(
        "SELECT date, contract, daily_return FROM futures_quotes WHERE date <= ? ORDER BY date DESC, contract LIMIT 80",
        (run_date,),
    ).fetchall()[::-1]
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    levels: dict[str, float] = defaultdict(lambda: 100.0)
    for row in rows:
        contract = str(row["contract"])
        levels[contract] *= 1 + float(row["daily_return"])
        grouped[contract].append((str(row["date"])[5:], levels[contract]))
    return _write_line_chart(asset_dir / f"{run_date}_futures_20d.svg", "国债期货累计表现", grouped, "指数")


def _curve_chart(conn, run_date, asset_dir):
    dates = [row["date"] for row in conn.execute(
        "SELECT DISTINCT date FROM bond_yields WHERE date <= ? ORDER BY date DESC LIMIT 2", (run_date,)
    )]
    order = {"1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "30Y": 30}
    grouped: dict[str, list[tuple[str, float]]] = {}
    for value_date in dates:
        rows = conn.execute("SELECT tenor, yield_value FROM bond_yields WHERE date=?", (value_date,)).fetchall()
        grouped[str(value_date)] = [
            (str(row["tenor"]), float(row["yield_value"]))
            for row in sorted(rows, key=lambda item: order.get(str(item["tenor"]), 999))
        ]
    return _write_line_chart(asset_dir / f"{run_date}_yield_curve.svg", "国债收益率曲线", grouped, "%")


def _funding_chart(conn, run_date, asset_dir):
    rows = conn.execute(
        "SELECT date, rate_name, rate_value FROM funding_rates WHERE date <= ? ORDER BY date DESC LIMIT 100",
        (run_date,),
    ).fetchall()[::-1]
    wanted = {"DR007", "FDR007", "R007", "FR007", "SHIBOR_7D"}
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        if row["rate_name"] in wanted:
            grouped[str(row["rate_name"])].append((str(row["date"])[5:], float(row["rate_value"])))
    return _write_line_chart(asset_dir / f"{run_date}_funding_20d.svg", "近20日资金利率分层", grouped, "%")


def _macro_chart(conn, run_date, asset_dir):
    rows = conn.execute(
        "SELECT period, indicator, value FROM macro_history WHERE date=? ORDER BY period", (run_date,)
    ).fetchall()
    top: dict[str, list[tuple[str, float]]] = defaultdict(list)
    bottom: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        target = bottom if row["indicator"] == "PMI_MFG" else top
        target[str(row["indicator"])].append((str(row["period"])[2:], float(row["value"])))
    path = asset_dir / f"{run_date}_macro_history.svg"
    first = _svg_chart_body(760, 250, "CPI/PPI 同比（%）", top, 45)
    second = _svg_chart_body(760, 250, "制造业 PMI（荣枯线=50）", bottom, 315)
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="570" viewBox="0 0 760 570">'
        '<rect width="100%" height="100%" fill="white"/><text x="58" y="25" '
        'font-family="sans-serif" font-size="18" font-weight="700">近6期宏观数据</text>'
        + first + second + '</svg>', encoding="utf-8"
    )
    return path


def _write_line_chart(path: Path, title: str, series, unit: str) -> Path:
    body = _svg_chart_body(760, 360, title, series, 45, unit)
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="410" viewBox="0 0 760 410">'
        '<rect width="100%" height="100%" fill="white"/>' + body + '</svg>', encoding="utf-8"
    )
    return path


def _svg_chart_body(width: int, height: int, title: str, series, y_offset: int, unit: str = "") -> str:
    data = [(name, points) for name, points in series.items() if points]
    if not data:
        return f'<text x="{width/2}" y="{y_offset+height/2}" text-anchor="middle" font-family="sans-serif">无可用数据</text>'
    values = [value for _, points in data for _, value in points]
    low, high = min(values), max(values)
    padding = max((high - low) * 0.12, 0.05)
    low, high = low - padding, high + padding
    labels = list(dict.fromkeys(label for _, points in data for label, _ in points))
    labels.sort(key=lambda label: float(label.rstrip("Y")) if label.endswith("Y") else label)
    positions = {label: index for index, label in enumerate(labels)}
    left, right, top, bottom = 62, width - 28, y_offset + 62, y_offset + height - 40
    parts = [
        f'<text x="{left}" y="{y_offset+15}" font-family="sans-serif" fill="#1e293b" font-size="18" font-weight="600">{html.escape(title)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#94a3b8"/>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#94a3b8"/>',
    ]
    for tick in range(5):
        value = low + (high - low) * tick / 4
        y = bottom - (bottom - top) * tick / 4
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#e8edf2"/>')
        parts.append(f'<text x="{left-9}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" fill="#64748b" font-size="12">{value:.2f}</text>')
    parts.append(f'<text x="{right}" y="{y_offset+15}" text-anchor="end" font-family="sans-serif" fill="#64748b" font-size="12">{html.escape(unit)}</text>')
    for index, (name, points) in enumerate(data):
        coords = []
        for label, value in points:
            x = left + (right - left) * positions[label] / max(len(labels) - 1, 1)
            y = bottom - (bottom - top) * (value - low) / (high - low)
            coords.append(f"{x:.1f},{y:.1f}")
        color = COLORS[index % len(COLORS)]
        dash = ' stroke-dasharray="7 4"' if index % 2 else ''
        parts.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2.4"{dash}/>')
        for coord in coords:
            x, y = coord.split(',')
            parts.append(f'<circle cx="{x}" cy="{y}" r="2.8" fill="white" stroke="{color}" stroke-width="1.5"/>')
        parts.append(f'<text x="{left + index*132}" y="{y_offset+40}" font-family="sans-serif" font-size="13" fill="{color}">{html.escape(str(name))}</text>')
    step = max(1, len(labels) // 5)
    for index, label in enumerate(labels):
        if index % step == 0 or index == len(labels) - 1:
            x = left + (right - left) * index / max(len(labels) - 1, 1)
            parts.append(f'<text x="{x:.1f}" y="{bottom+23}" text-anchor="middle" font-family="sans-serif" fill="#64748b" font-size="12">{html.escape(label)}</text>')
    return "".join(parts)

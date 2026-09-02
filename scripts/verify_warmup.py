"""Read-only, reproducible acceptance checks for the 2026 warmup rebuild."""

from __future__ import annotations

import json
import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from bond_futures_monitor.database import connect
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.daily_report import generate_daily_report, validate_report_tables
from bond_futures_monitor.validation import validate_real_data_coverage


LEVEL_CHANGES = ("yield_10y_change", "yield_30y_change", "dr007_change", "avg_volume_change")
ROLLING_VALUES = ("yield_10y_change_percentile_60d", "funding_change_percentile_60d",
                  "futures_return_percentile_20d", "volume_ratio_20d",
                  "open_interest_ratio_20d", "open_interest_change_1d")


def snapshot(conn, day):
    row = dict(conn.execute("SELECT * FROM daily_features WHERE date=?", (day,)).fetchone())
    rolling = json.loads(row["details_json"])["rolling_context"]
    return {"date": day, "missing_level_changes": sum(row[k] is None for k in LEVEL_CHANGES),
            "missing_rolling_values": sum(rolling[k] is None for k in ROLLING_VALUES),
            "changes": {k: row[k] for k in LEVEL_CHANGES}, "rolling": rolling}


def verify(root: Path, render_reports: bool = False):
    output = root / "reports_output"
    manifest = json.loads((output / "backfill_2026_manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] == manifest["expected_dates"]
    assert not manifest["failed"] and not manifest["warmup_failed"]
    assert len(manifest["warmup_completed"]) == 120
    dates = manifest["completed"]
    first = dates[0]
    backup = root / "data" / f"backfill_2026_{manifest['end']}" / "before_warmup_backfill.db"
    assert backup.is_file(), "Pre-warmup baseline backup is missing"
    with connect(backup) as old:
        before = snapshot(old, first)
    charts = 0
    table_cells = 0
    activity_comparisons = 0
    with connect(root / "data/bond_futures_monitor.db") as conn:
        after = snapshot(conn, first)
        seed = manifest["warmup_dates"][:60]
        scored = manifest["warmup_dates"][60:]
        for day in seed:
            assert not conn.execute("SELECT 1 FROM daily_market_signals WHERE date=?", (day,)).fetchone()
        for day in scored + dates:
            validate_real_data_coverage(conn, day)
            row = snapshot(conn, day)
            assert row["missing_level_changes"] == row["missing_rolling_values"] == 0, row
            assert row["rolling"]["yield_change_observations"] == 60, day
            assert row["rolling"]["funding_change_observations"] == 60, day
            assert row["rolling"]["history_days"] == 20, day
            stored = json.loads(conn.execute("SELECT details_json FROM daily_features WHERE date=?", (day,)).fetchone()[0])
            assert stored == build_daily_features(conn, day)["details"], day
        for day in dates:
            if render_reports:
                generate_daily_report(conn, day, output)
            content = (output / f"{day}_daily_report.md").read_text(encoding="utf-8")
            table_cells += validate_report_tables(content)
            # Required, warmed-up market panels must contain values, not even
            # explanatory fallback text. Optional-source caveats remain visible.
            for start, end in (("### 关键数字", "## 期货表现"),
                               ("| 合约 | 日收益 |", "*均值取"),
                               ("| 结构 | 当前 |", "*图中期限")):
                panel = content.split(start, 1)[1].split(end, 1)[0]
                for line in panel.splitlines():
                    if not line.startswith("|") or line.startswith("|---"):
                        continue
                    cells = [s.strip() for s in line.split("|")[1:-1]]
                    if cells[0] in ("指标", "结构", "合约"):
                        continue
                    numeric_cells = cells[1:-1] if cells[0] in ("TS", "TF", "T", "TL") else cells[1:]
                    assert all(re.fullmatch(r"[+-]?[\d,.]+(?:%| bp|x)?", c) for c in numeric_cells), (day, line)
            activity = conn.execute(
                "SELECT date,SUM(volume) AS volume,SUM(open_interest) AS oi FROM futures_quotes "
                "WHERE date<=? GROUP BY date ORDER BY date DESC LIMIT 6", (day,)).fetchall()
            assert len(activity) == 6
            for label, field in (("总成交量", "volume"), ("总持仓量", "oi")):
                line = next(s for s in content.splitlines() if s.startswith(f"| {label} |"))
                cells = [s.strip() for s in line.split("|")[1:-1]]
                for position, offset in ((2, 1), (3, 5)):
                    expected = f"{activity[0][field]/activity[offset][field]-1:+.1%}"
                    assert cells[position] == expected, (day, label, expected, cells[position])
                    activity_comparisons += 1
            assert "历史重建版" in content
            paths = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content)
            assert len(paths) == 4
            for path in paths:
                svg = ET.parse(output / path)
                for line in svg.iter("{http://www.w3.org/2000/svg}polyline"):
                    x = [float(pair.split(",")[0]) for pair in line.attrib["points"].split()]
                    assert x == sorted(x), (day, path, "non-chronological chart")
                charts += 1
        # Independently recompute first-day deltas from the two source snapshots.
        previous = manifest["warmup_dates"][-1]
        for tenor, key in (("10Y", "yield_10y_change"), ("30Y", "yield_30y_change")):
            values = dict(conn.execute("SELECT date,yield_value FROM bond_yields WHERE tenor=? AND date IN (?,?)",
                                       (tenor, previous, first)))
            assert abs(after["changes"][key] - (values[first] - values[previous])) < 1e-12
        future = conn.execute("SELECT COUNT(*) FROM macro_history WHERE release_date>date").fetchone()[0]
        assert future == 0
        optional = {name: sum(not conn.execute(f"SELECT 1 FROM {name} WHERE date=?", (day,)).fetchone()
                             for day in dates) for name in manifest["missing_optional_dates"]}
        counts = {table: conn.execute(f"SELECT COUNT(DISTINCT date) FROM {table} WHERE date<?", (first,)).fetchone()[0]
                  for table in ("futures_quotes", "bond_yields", "funding_rates", "daily_market_signals")}
    return {"scope": {"first": first, "last": dates[-1], "reports": len(dates), "charts": charts,
                       "warmup_start": manifest["warmup_dates"][0], "warmup_end": previous},
            "before": before, "after": after, "pre_report_date_counts": counts,
            "complete_rolling_windows": len(scored) + len(dates), "future_macro_rows": future,
            "report_table_cells_checked": table_cells,
            "activity_comparisons_recomputed": activity_comparisons,
            "unexplained_table_cells": 0,
            "missing_optional_dates": optional,
            "limitations": ["Historical news and issuance-calendar gaps are not repaired by market-data warmup.",
                            "ChinaBond fallback 2Y is interpolated from 1Y/3Y, not directly published.",
                            "Past score direction checks are in-sample diagnostics, not a trading backtest."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-reports", action="store_true", help="Regenerate reports from stored data before checking")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = verify(root, render_reports=args.render_reports)
    path = root / "reports_output/2026_warmup_validation.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

"""Read-only, reproducible acceptance checks for the 2026 warmup rebuild."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from bond_futures_monitor.database import connect
from bond_futures_monitor.features.daily_features import build_daily_features
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


def verify(root: Path):
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
            content = (output / f"{day}_daily_report.md").read_text(encoding="utf-8")
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
        optional = {name: len(days) for name, days in manifest["missing_optional_dates"].items()}
        counts = {table: conn.execute(f"SELECT COUNT(DISTINCT date) FROM {table} WHERE date<?", (first,)).fetchone()[0]
                  for table in ("futures_quotes", "bond_yields", "funding_rates", "daily_market_signals")}
    return {"scope": {"first": first, "last": dates[-1], "reports": len(dates), "charts": charts,
                       "warmup_start": manifest["warmup_dates"][0], "warmup_end": previous},
            "before": before, "after": after, "pre_report_date_counts": counts,
            "complete_rolling_windows": len(scored) + len(dates), "future_macro_rows": future,
            "missing_optional_dates": optional,
            "limitations": ["Historical news and issuance-calendar gaps are not repaired by market-data warmup.",
                            "ChinaBond fallback 2Y is interpolated from 1Y/3Y, not directly published.",
                            "Past score direction checks are in-sample diagnostics, not a trading backtest."]}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    result = verify(root)
    path = root / "reports_output/2026_warmup_validation.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

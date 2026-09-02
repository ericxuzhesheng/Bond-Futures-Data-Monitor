"""Recheck stored news OMO against date-scope rules; backup before applying."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from bond_futures_monitor import database as db
from bond_futures_monitor.collectors.open_market import parse_omo_text
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.csv_export import export_features_csv
from bond_futures_monitor.signals.rule_based import generate_market_signal


def repair(root: Path, apply: bool = False):
    output = root / "reports_output"
    manifest = json.loads((output / "backfill_2026_manifest.json").read_text(encoding="utf-8"))
    dates = manifest["completed"]
    backup = root / "data" / f"backfill_2026_{manifest['end']}" / "before_report_cell_repair.db"
    journal = output / "2026_omo_scope_repair.json"
    with db.connect(root / "data/bond_futures_monitor.db") as conn:
        rejected, unmatched = [], []
        for row in conn.execute(
            "SELECT rowid AS stored_id,* FROM open_market_operations "
            "WHERE date BETWEEN ? AND ? AND data_source LIKE 'tushare_news_cls:%'",
            (dates[0], dates[-1]),
        ).fetchall():
            news = conn.execute("SELECT title,content FROM policy_news WHERE date=? AND title=?",
                                (row["date"], row["source_title"])).fetchone()
            if news is None:
                unmatched.append({"date": row["date"], "title": row["source_title"]})
                continue
            if not parse_omo_text(row["date"], news["title"], news["content"], row["data_source"]):
                rejected.append(dict(row))
        result = {"applied": apply, "removed_records": rejected, "unmatched_news": unmatched,
                  "affected_dates": sorted({r["date"] for r in rejected}),
                  "reason": "Weekly aggregates or planned operations are not same-day realized OMO."}
        if not apply or not rejected:
            return result
        if backup.exists() or journal.exists():
            raise RuntimeError("Repair evidence already exists; do not overwrite the recovery snapshot")
        with sqlite3.connect(backup) as destination:
            conn.backup(destination)
        with conn:
            for row in rejected:
                conn.execute("DELETE FROM open_market_operations WHERE rowid=?", (row["stored_id"],))
            for day in result["affected_dates"]:
                remaining = conn.execute("SELECT * FROM open_market_operations WHERE date=?", (day,)).fetchall()
                db.upsert_collection_status(conn, day, "open_market_operations",
                    "partial" if remaining else "unavailable", len(remaining),
                    ", ".join(sorted({r["data_source"] for r in remaining})) or "none",
                    "已剔除周度汇总或未来操作计划的误采记录；仅保留原有当日记录，不将未知操作补为零", day)
                features = build_daily_features(conn, day)
                db.upsert_daily_features(conn, features)
                db.upsert_daily_market_signal(conn, generate_market_signal(features))
            bad_rates = conn.execute(
                "SELECT date FROM open_market_operations WHERE date BETWEEN ? AND ? "
                "AND (operation_rate<0 OR operation_rate>20)", (dates[0], dates[-1])).fetchall()
            if bad_rates:
                raise RuntimeError(f"Unresolved invalid operation rates: {[r[0] for r in bad_rates]}")
        journal.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.setdefault("missing_optional_dates", {})["open_market_operations"] = [
            day for day in dates
            if not conn.execute("SELECT 1 FROM open_market_operations WHERE date=?", (day,)).fetchone()
        ]
        (output / "backfill_2026_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        export_features_csv(conn, output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = repair(Path(__file__).resolve().parents[1], args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))

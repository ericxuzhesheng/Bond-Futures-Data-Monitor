"""Command-line interface for the bond futures monitor."""

from __future__ import annotations

import argparse
from datetime import date

from bond_futures_monitor.ai.text_signal import classify_news_item
from bond_futures_monitor.collectors.funding import collect_funding_rates
from bond_futures_monitor.collectors.futures import collect_futures_quotes
from bond_futures_monitor.collectors.policy_news import collect_policy_news
from bond_futures_monitor.collectors.yield_curve import collect_bond_yields
from bond_futures_monitor.config import get_settings
from bond_futures_monitor.database import (
    connect,
    fetch_policy_news,
    init_db,
    insert_ai_text_signal,
    insert_bond_yields,
    insert_funding_rates,
    insert_futures_quotes,
    insert_policy_news,
    log_run,
    purge_sample_fallback_for_date,
    upsert_daily_features,
    upsert_daily_market_signal,
)
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.daily_report import generate_daily_report
from bond_futures_monitor.signals.rule_based import generate_market_signal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="China Treasury bond futures data monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the SQLite database")

    run_parser = subparsers.add_parser("run", help="Run the full daily pipeline")
    run_parser.add_argument("--date", default=date.today().isoformat(), help="Run date in YYYY-MM-DD format")

    report_parser = subparsers.add_parser("generate-report", help="Generate daily Markdown report")
    report_parser.add_argument("--date", default=date.today().isoformat(), help="Report date in YYYY-MM-DD format")

    args = parser.parse_args(argv)
    settings = get_settings()

    with connect(settings.database_path) as conn:
        if args.command == "init-db":
            init_db(conn)
            print(f"数据库已初始化：{settings.database_path}")
            return 0

        if args.command == "run":
            init_db(conn)
            try:
                run_daily_pipeline(conn, args.date, settings.use_live_data, settings.reports_output_dir)
                log_run(conn, args.date, "success", "Daily pipeline completed")
                print(f"每日监控流程已完成：{args.date}")
                print(f"日报已生成：{settings.reports_output_dir / f'{args.date}_daily_report.md'}")
                return 0
            except Exception as exc:
                log_run(conn, args.date, "failed", str(exc))
                raise

        if args.command == "generate-report":
            path = generate_daily_report(conn, args.date, settings.reports_output_dir)
            print(f"日报已生成：{path}")
            return 0

    return 1


def run_daily_pipeline(conn, run_date: str, use_live_data: bool, reports_output_dir) -> None:
    if use_live_data:
        purge_sample_fallback_for_date(conn, run_date)

    insert_futures_quotes(conn, collect_futures_quotes(run_date, use_live_data))
    insert_bond_yields(conn, collect_bond_yields(run_date, use_live_data))
    insert_funding_rates(conn, collect_funding_rates(run_date, use_live_data))
    insert_policy_news(conn, collect_policy_news(run_date, use_live_data))

    for row in fetch_policy_news(conn, run_date):
        insert_ai_text_signal(conn, classify_news_item(dict(row)))

    features = build_daily_features(conn, run_date)
    upsert_daily_features(conn, features)

    signal = generate_market_signal(features)
    upsert_daily_market_signal(conn, signal)

    generate_daily_report(conn, run_date, reports_output_dir)


if __name__ == "__main__":
    raise SystemExit(main())

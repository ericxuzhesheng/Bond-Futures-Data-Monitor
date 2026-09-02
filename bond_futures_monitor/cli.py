"""Command-line interface for the bond futures monitor."""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bond_futures_monitor.ai.text_signal import classify_news_item
from bond_futures_monitor.collectors.curve_comparison import collect_yield_curve_comparison_result
from bond_futures_monitor.collectors.funding import collect_funding_rates
from bond_futures_monitor.collectors.futures import collect_futures_quotes
from bond_futures_monitor.collectors.macro import collect_macro_indicators
from bond_futures_monitor.collectors.news_feed import get_cls_news_status
from bond_futures_monitor.collectors.macro_history import collect_nbs_macro_history_result
from bond_futures_monitor.collectors.open_market import collect_open_market_operations
from bond_futures_monitor.collectors.policy_news import collect_policy_news
from bond_futures_monitor.collectors.treasury_calendar import collect_treasury_issuance_calendar_result
from bond_futures_monitor.collectors.yield_curve import collect_bond_yields
from bond_futures_monitor.config import get_settings
from bond_futures_monitor.database import (
    connect,
    fetch_policy_news,
    init_db,
    insert_ai_text_signals,
    insert_bond_yields,
    insert_funding_rates,
    insert_futures_quotes,
    insert_macro_indicators,
    insert_macro_history,
    insert_open_market_operations,
    insert_policy_news,
    insert_treasury_issuance_calendar,
    insert_yield_curve_comparisons,
    log_run,
    purge_daily_data_for_date,
    purge_superseded_ai_signals_for_date,
    upsert_daily_features,
    upsert_daily_market_signal,
    upsert_collection_status,
)
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.csv_export import export_features_csv
from bond_futures_monitor.reports.daily_report import generate_daily_report
from bond_futures_monitor.signals.rule_based import generate_market_signal
from bond_futures_monitor.validation import validate_real_data_coverage


logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="China Treasury bond futures real-data monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the SQLite database")

    run_parser = subparsers.add_parser("run", help="Run the full daily real-data pipeline")
    run_parser.add_argument("--date", default="today", help="Run date in YYYY-MM-DD format, or 'today'")

    report_parser = subparsers.add_parser("generate-report", help="Generate daily Markdown report")
    report_parser.add_argument("--date", default="today", help="Report date in YYYY-MM-DD format, or 'today'")

    args = parser.parse_args(argv)
    settings = get_settings()
    if hasattr(args, "date"):
        args.date = resolve_run_date(args.date)

    with connect(settings.database_path) as conn:
        if args.command == "init-db":
            init_db(conn)
            print(f"数据库已初始化：{settings.database_path}")
            return 0

        if args.command == "run":
            init_db(conn)
            try:
                run_daily_pipeline(conn, args.date, settings.use_live_data, settings.reports_output_dir)
                log_run(conn, args.date, "success", "Daily real-data pipeline completed")
                generate_daily_report(conn, args.date, settings.reports_output_dir)
                csv_path = export_features_csv(conn, settings.reports_output_dir)
                print(f"每日真实数据监控流程已完成：{args.date}")
                print(f"日报已生成：{settings.reports_output_dir / f'{args.date}_daily_report.md'}")
                print(f"特征时间序列已导出：{csv_path}")
                return 0
            except Exception as exc:
                # The pipeline purges the run date before refreshing, so a partial
                # run is self-healing on the next rerun; log the failure for ops.
                logger.error("Daily pipeline failed for %s: %s", args.date, exc)
                log_run(conn, args.date, "failed", str(exc))
                raise

        if args.command == "generate-report":
            path = generate_daily_report(conn, args.date, settings.reports_output_dir)
            csv_path = export_features_csv(conn, settings.reports_output_dir)
            print(f"日报已生成：{path}")
            print(f"特征时间序列已导出：{csv_path}")
            return 0

    return 1


def run_daily_pipeline(conn, run_date: str, use_live_data: bool, reports_output_dir) -> None:
    if not use_live_data:
        raise RuntimeError("USE_LIVE_DATA=0 is not allowed because production output requires real data.")

    # Keep the previous complete snapshot if any collector, validation, or
    # downstream calculation fails. The caller can then safely retry the date.
    with conn:
        purge_daily_data_for_date(conn, run_date)

        core = [
            ("futures_quotes", collect_futures_quotes(run_date, use_live_data), insert_futures_quotes),
            ("bond_yields", collect_bond_yields(run_date, use_live_data), insert_bond_yields),
            ("funding_rates", collect_funding_rates(run_date, use_live_data), insert_funding_rates),
            ("open_market_operations", collect_open_market_operations(run_date, use_live_data), insert_open_market_operations),
            ("policy_news", collect_policy_news(run_date, use_live_data), insert_policy_news),
            ("macro_indicators", collect_macro_indicators(run_date, use_live_data), insert_macro_indicators),
        ]
        for dataset, rows, inserter in core:
            inserter(conn, rows)
            sources = sorted({str(row.get("data_source", "unknown")) for row in rows})
            status = "ok" if rows else "empty"
            message = "采集成功" if rows else "当日未返回记录"
            if dataset == "policy_news" and not rows:
                status, message = get_cls_news_status(run_date)
            upsert_collection_status(
                conn, run_date, dataset, status, len(rows),
                ", ".join(sources) or "none", message,
                run_date,
            )

        optional = [
            ("macro_history", collect_nbs_macro_history_result(run_date), insert_macro_history),
            ("treasury_issuance_calendar", collect_treasury_issuance_calendar_result(run_date), insert_treasury_issuance_calendar),
            ("yield_curve_comparisons", collect_yield_curve_comparison_result(run_date), insert_yield_curve_comparisons),
        ]
        for dataset, result, inserter in optional:
            inserter(conn, result.rows)
            upsert_collection_status(
                conn, run_date, dataset, result.status, len(result.rows), result.source,
                result.message[:500], result.observation_date,
            )

        # These research fields require inputs that the verified public sources do
        # not publish as a complete historical set. Explicit states prevent an
        # absent value from being mistaken for zero or "no event".
        unavailable = {
            "ctd_basis_irr": "缺少逐合约可交割券、转换因子与现券净价，不做估算",
            "treasury_auction_results": "尚无经验证的历史招标结果结构化源",
            "cross_market": "外围公开接口当前连接不稳定，不纳入生产评分",
            "funding_ncd_irs": "AAA同业存单与FR007 IRS历史接口尚未通过稳定性验证，不与回购利率混用",
        }
        for dataset, message in unavailable.items():
            upsert_collection_status(conn, run_date, dataset, "unavailable", 0, "none", message)
        validate_real_data_coverage(conn, run_date)

        signals = [classify_news_item(dict(row)) for row in fetch_policy_news(conn, run_date)]
        insert_ai_text_signals(conn, signals)
        purge_superseded_ai_signals_for_date(conn, run_date)

        features = build_daily_features(conn, run_date)
        upsert_daily_features(conn, features)

        signal = generate_market_signal(features)
        upsert_daily_market_signal(conn, signal)


def resolve_run_date(value: str) -> str:
    """Resolve a CLI date argument."""

    if value.lower() == "today":
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    date.fromisoformat(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())

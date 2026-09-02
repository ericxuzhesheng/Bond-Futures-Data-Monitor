"""Resumable historical rebuild; shared histories are fetched only once.

Existing market/news snapshots are retained. Monthly macro values are rebuilt
from dated official releases, never from the latest revised monthly API table.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from bond_futures_monitor import database as db
from bond_futures_monitor.ai.text_signal import classify_news_item
from bond_futures_monitor.collectors.funding import _rows_from_akshare_repo, _rows_from_akshare_shibor
from bond_futures_monitor.collectors.futures import CONTRACTS, _collect_cffex_daily, _sina_row
from bond_futures_monitor.collectors.macro import _akshare_lpr_rows, _validated_value
from bond_futures_monitor.collectors.macro_history import _collect_nbs_macro_history
from bond_futures_monitor.collectors.yield_curve import REQUIRED_TENORS, _validated_yield
from bond_futures_monitor.config import get_settings
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.csv_export import export_features_csv
from bond_futures_monitor.reports.daily_report import generate_daily_report
from bond_futures_monitor.signals.rule_based import generate_market_signal
from bond_futures_monitor.validation import validate_real_data_coverage

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def rows(self, name, fetch):
        path = self.root / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        logger.info("Fetching %s", name)
        rows = fetch()
        if not rows:
            raise RuntimeError(f"No historical records: {name}")
        # Failed/empty responses are not cached, so the next invocation retries.
        path.write_text(json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
        return rows

    def frame(self, name, fetch):
        return pd.DataFrame(self.rows(name, lambda: fetch().to_dict("records")))


def closed_end(year: int, now: datetime | None = None) -> str:
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    # Wait for the regular 19:01 publication window, not an intraday snapshot.
    available = now.date() if (now.hour, now.minute) >= (19, 1) else now.date() - timedelta(days=1)
    end = min(date(year, 12, 31), available)
    if end < date(year, 1, 1):
        raise ValueError("Cannot backfill a future year")
    return end.isoformat()


def release_rows(releases, run_date: str, periods: int = 6):
    selected = []
    for indicator in ("CPI_YOY", "PPI_YOY", "PMI_MFG"):
        eligible = [r for r in releases if r["indicator"] == indicator and r["release_date"] <= run_date]
        unique = {}
        for row in sorted(eligible, key=lambda r: (r["period"], r["release_date"]), reverse=True):
            unique.setdefault(row["period"], dict(row, date=run_date))
        selected.extend(list(unique.values())[:periods])
    return selected


def macro_rows(releases, lpr, run_date):
    rows = _akshare_lpr_rows(lpr, run_date, date.fromisoformat(run_date))
    for row in release_rows(releases, run_date, 1):
        rows.append({"date": run_date, "indicator": row["indicator"],
                     "period": row["period"], "value": _validated_value(row["indicator"], row["value"]),
                     "data_source": f"nbs_official_release:{row['release_date']}:{row['source_url']}"})
    if len(rows) != 5:
        raise RuntimeError(f"Missing point-in-time macro releases for {run_date}")
    return rows


def prepare(cache, year, end):
    import akshare as ak
    import tushare as ts

    start = f"{year}-01-01"
    pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])
    calendar = cache.frame("calendar", lambda: pro.trade_cal(
        exchange="CFFEX", start_date=start.replace("-", ""), end_date=end.replace("-", "")))
    observed = set(calendar["cal_date"].astype(str))
    expected = {(date.fromisoformat(start) + timedelta(days=i)).strftime("%Y%m%d")
                for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)}
    if not expected.issubset(observed):
        raise RuntimeError("Trading calendar is incomplete")
    dates = sorted(f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in
                   calendar.loc[calendar["is_open"].astype(int) == 1, "cal_date"].astype(str)
                   if start.replace("-", "") <= d <= end.replace("-", ""))
    shared = {"dates": dates}
    for contract in CONTRACTS:
        shared[contract] = cache.frame(f"sina_{contract}", lambda c=contract: ak.futures_zh_daily_sina(symbol=f"{c}0"))
    shared["shibor"] = cache.frame("shibor", ak.macro_china_shibor_all)
    shared["lpr"] = cache.frame("lpr", ak.macro_china_lpr)
    shared["releases"] = cache.rows("nbs_releases_v2", lambda: _collect_nbs_macro_history(end, periods=16, max_pages=40))
    logger.info("Calendar: %s sessions, %s to %s; NBS: %s releases", len(dates), dates[0], dates[-1], len(shared["releases"]))
    return shared


def month_bounds(run_date, end):
    start = run_date[:7] + "-01"
    next_month = (date.fromisoformat(start).replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, min((next_month - timedelta(days=1)).isoformat(), end)


def historical_omo(cache, dates):
    """Recover official operations only when prior notices establish maturities."""
    import requests
    from bs4 import BeautifulSoup
    from bond_futures_monitor.collectors.open_market import (
        PBC_OMO_LIST_URL, PBC_OMO_HISTORY_URL, _pbc_notice_links,
        _parse_zero_operation_notice, _merge_official_and_news_rows, parse_omo_text,
    )

    if not dates:
        return {}
    start = (date.fromisoformat(min(dates)) - timedelta(days=30)).isoformat()
    end = max(dates)
    links = {}
    session = requests.Session()

    def html(url):
        response = session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    for page in range(1, 21):
        url = PBC_OMO_LIST_URL if page == 1 else PBC_OMO_HISTORY_URL.format(page=page)
        try:
            content = cache.rows(f"pbc_list_{page}", lambda: [html(url)])[0]
        except Exception as exc:
            logger.warning("PBC list %s unavailable: %s", page, exc)
            break
        page_dates = []
        for td in BeautifulSoup(content, "html.parser").find_all("td"):
            text = td.get_text(" ", strip=True)
            if "公开市场业务交易公告 [" not in text:
                continue
            page_dates.extend(re.findall(r"20\d{2}-\d{2}-\d{2}", text))
        for day in set(page_dates):
            if start <= day <= end:
                links.setdefault(day, []).extend(_pbc_notice_links(content, day))
        if page_dates and min(page_dates) < start:
            break

    def notices(day):
        rows = []
        for index, (title, url) in enumerate(dict.fromkeys(links.get(day, []))):
            def fetch():
                text = BeautifulSoup(html(url), "html.parser").get_text(" ", strip=True)
                return parse_omo_text(day, title, text, f"pbc_official:{url}") or _parse_zero_operation_notice(
                    day, title, text, f"pbc_official:{url}")
            try:
                rows.extend(cache.rows(f"pbc_notice_{day}_{index}", fetch))
            except RuntimeError as exc:
                # A day can contain MLF/other notices alongside a reverse-repo
                # notice. Unsupported operation types must not hide the latter.
                if not str(exc).startswith("No historical records:"):
                    raise
        return rows

    result = {}
    for day in dates:
        try:
            rows = notices(day)
            for row in rows:
                tenor = row.get("tenor_days")
                if not isinstance(tenor, int) or tenor <= 0:
                    row["_net_complete"] = False
                    continue
                prior_day = (date.fromisoformat(day) - timedelta(days=tenor)).isoformat()
                prior = notices(prior_day)
                # No earlier notice is not evidence of zero maturity.
                row["_net_complete"] = bool(prior)
                maturity = sum(float(r["operation_amount"]) for r in prior
                               if r["tenor_days"] == tenor and r["operation_type"] == row["operation_type"])
                row["maturity_amount"] = maturity
                row["net_injection_amount"] = float(row["operation_amount"]) - maturity
            result[day] = _merge_official_and_news_rows(rows, [])
        except Exception as exc:
            logger.warning("Historical OMO %s unavailable: %s", day, exc)
            result[day] = []
    return result


def historical_yields(cache, shared, run_date):
    import akshare as ak

    compact = run_date.replace("-", "")
    rows = []
    # CFETS may restrict older history. After an empty response, use the
    # independently published ChinaBond monthly history for that month.
    if run_date[:7] not in shared.setdefault("cfets_unavailable_months", set()):
        try:
            curve = cache.frame(f"curve_{run_date}", lambda: ak.bond_china_close_return(
                symbol="国债", period="1", start_date=compact, end_date=compact))
            day = curve[curve["日期"].astype(str) == run_date]
            for term, tenor in REQUIRED_TENORS.items():
                matched = day[(day["期限"].astype(float) - term).abs() < .01]
                if not matched.empty:
                    rows.append({"date": run_date, "tenor": tenor,
                                 "yield_value": _validated_yield(tenor, matched.iloc[0]["到期收益率"]),
                                 "data_source": f"akshare_bond_china_close_return:{run_date}"})
            if len(rows) == 5:
                return rows
        except Exception as exc:
            logger.warning("CFETS history unavailable %s: %s", run_date, exc)
        shared["cfets_unavailable_months"].add(run_date[:7])
    start, end = month_bounds(run_date, shared["dates"][-1])
    curve = cache.frame(f"chinabond_{run_date[:7]}", lambda: ak.bond_china_yield(
        start_date=start.replace("-", ""), end_date=end.replace("-", "")))
    day = curve[(curve["日期"].astype(str) == run_date) & (curve["曲线名称"] == "中债国债收益率曲线")]
    if day.empty:
        raise RuntimeError(f"No same-day ChinaBond curve: {run_date}")
    row = day.iloc[0]
    values = {"1Y": row["1年"], "2Y": (float(row["1年"]) + float(row["3年"])) / 2,
              "5Y": row["5年"], "10Y": row["10年"], "30Y": row["30年"]}
    return [{"date": run_date, "tenor": tenor, "yield_value": _validated_yield(tenor, value),
             "data_source": f"akshare_bond_china_yield:{run_date}" + (":interpolated_1y_3y" if tenor == "2Y" else "")}
            for tenor, value in values.items()]


def collect_missing(conn, cache, shared, run_date):
    import akshare as ak

    if conn.execute("SELECT COUNT(*) FROM futures_quotes WHERE date=?", (run_date,)).fetchone()[0] < 4:
        def fetch_futures():
            quotes = {r["contract"]: r for r in _collect_cffex_daily(run_date)}
            for contract in CONTRACTS:
                if contract in quotes:
                    continue
                history = shared[contract].sort_values("date").reset_index(drop=True)
                matches = history.index[history["date"].astype(str) == run_date]
                if len(matches):
                    quotes[contract] = _sina_row(run_date, contract, f"{contract}0", history, int(matches[-1]))
            if len(quotes) != 4:
                raise RuntimeError(f"Incomplete futures history on {run_date}")
            return list(quotes.values())
        db.insert_futures_quotes(conn, cache.rows(f"futures_{run_date}", fetch_futures))

    if conn.execute("SELECT COUNT(*) FROM bond_yields WHERE date=?", (run_date,)).fetchone()[0] < 5:
        db.insert_bond_yields(conn, historical_yields(cache, shared, run_date))

    if conn.execute("SELECT COUNT(*) FROM funding_rates WHERE date=?", (run_date,)).fetchone()[0] < 5:
        month_start, month_end = month_bounds(run_date, shared["dates"][-1])
        repo = cache.frame(f"repo_{run_date[:7]}", lambda: ak.repo_rate_hist(
            start_date=month_start.replace("-", ""), end_date=month_end.replace("-", "")))
        rows = _rows_from_akshare_repo(repo, run_date) + _rows_from_akshare_shibor(shared["shibor"], run_date)
        db.insert_funding_rates(conn, rows)


def rebuild_day(conn, cache, shared, run_date):
    with conn:
        collect_missing(conn, cache, shared, run_date)
        db.insert_macro_indicators(conn, macro_rows(shared["releases"], shared["lpr"], run_date))
        db.insert_macro_history(conn, release_rows(shared["releases"], run_date))
        db.insert_open_market_operations(conn, shared.get("omo", {}).get(run_date, []))
        for table in ("futures_quotes", "bond_yields", "funding_rates", "macro_indicators", "macro_history",
                      "open_market_operations", "policy_news", "treasury_issuance_calendar", "yield_curve_comparisons"):
            rows = conn.execute(f"SELECT * FROM {table} WHERE date=?", (run_date,)).fetchall()
            existing = conn.execute("SELECT 1 FROM collection_status WHERE date=? AND dataset=?", (run_date, table)).fetchone()
            if table in ("treasury_issuance_calendar", "yield_curve_comparisons") and existing:
                continue
            sources = sorted({r["data_source"] for r in rows}) if rows and "data_source" in rows[0].keys() else []
            status = "ok" if rows else "unavailable"
            message = "历史数据重建；保留已有真实记录" if rows else "历史源未补齐；不代表当日无事件，不用现值填补"
            observation = max((r["release_date"] for r in rows), default=None) if table == "macro_history" else None
            if table == "macro_history" and len(rows) < 18:
                status = "partial" if rows else "unavailable"
            db.upsert_collection_status(conn, run_date, table, status, len(rows), ", ".join(sources) or "none", message, observation)
        for table in ("ctd_basis_irr", "treasury_auction_results", "cross_market", "funding_ncd_irs"):
            db.upsert_collection_status(conn, run_date, table, "unavailable", 0, "none", "未取得经验证的历史数据，不作估算")
        validate_real_data_coverage(conn, run_date)
        db.insert_ai_text_signals(conn, [classify_news_item(dict(r)) for r in db.fetch_policy_news(conn, run_date)])
        db.purge_superseded_ai_signals_for_date(conn, run_date)
        features = build_daily_features(conn, run_date)
        db.upsert_daily_features(conn, features)
        db.upsert_daily_market_signal(conn, generate_market_signal(features))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    end = closed_end(args.year)
    cache = Cache(Path("data") / f"backfill_{args.year}_{end}")
    shared = prepare(cache, args.year, end)
    if args.prepare_only:
        for run_date in (shared["dates"][0], shared["dates"][-1]):
            print(run_date, macro_rows(shared["releases"], shared["lpr"], run_date), flush=True)
        return 0
    manifest = {"year": args.year, "end": end, "expected_dates": shared["dates"], "completed": [], "failed": {},
                "mode": "reuse real market/news snapshots; rebuild point-in-time macro, features, signals and reports",
                "optional_limits": "OMO requires official operation/maturity notices; uncached historical news, treasury calendar and curve comparisons remain explicitly unavailable"}
    settings.reports_output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.reports_output_dir / f"backfill_{args.year}_manifest.json"
    with db.connect(settings.database_path) as conn:
        backup = cache.root / "before_backfill.db"
        if not backup.exists():
            with sqlite3.connect(backup) as dest:
                conn.backup(dest)
        db.init_db(conn)
        missing_omo = [d for d in shared["dates"] if not conn.execute(
            "SELECT 1 FROM open_market_operations WHERE date=?", (d,)).fetchone()]
        shared["omo"] = historical_omo(cache, missing_omo)
        for index, run_date in enumerate(shared["dates"], 1):
            try:
                rebuild_day(conn, cache, shared, run_date)
                db.log_run(conn, run_date, "success", "Historical rebuild with publication-date macro cutoff")
                generate_daily_report(conn, run_date, settings.reports_output_dir)
                manifest["completed"].append(run_date)
                logger.info("[%s/%s] completed %s", index, len(shared["dates"]), run_date)
            except Exception as exc:
                manifest["failed"][run_date] = str(exc)
                logger.exception("[%s/%s] failed %s", index, len(shared["dates"]), run_date)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        export_features_csv(conn, settings.reports_output_dir)
        manifest["missing_optional_dates"] = {
            table: [d for d in shared["dates"] if not conn.execute(
                f"SELECT 1 FROM {table} WHERE date=?", (d,)).fetchone()]
            for table in ("open_market_operations", "policy_news", "treasury_issuance_calendar", "yield_curve_comparisons")
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# {args.year} 年国债期货日报", "",
             f"截至 {end}，按中金所交易日历应有 {len(shared['dates'])} 期；本次完成 {len(manifest['completed'])} 期。", "",
             "采用新版排版与当前评分规则回溯重建，不是当年实际发布的版本。月度宏观按官方发布日期截断。", "",
             "未缓存的历史新闻及部分补充数据仍缺失，详见每期附录及 [回跑清单](" + manifest_path.name + ")。", "",
             "部分历史曲线使用中债备用源，2年期为1年与3年线性插值；不能视为直接发布值。", ""]
    month = None
    for d in shared["dates"]:
        if d[:7] != month:
            month = d[:7]
            lines.extend([f"## {month}", ""])
        lines.append(f"- [{d}]({d}_daily_report.md)" if d in manifest["completed"] else f"- {d}：本次失败，见回跑清单")
        if d == shared["dates"][-1] or shared["dates"][shared["dates"].index(d) + 1][:7] != month:
            lines.append("")
    (settings.reports_output_dir / f"{args.year}_index.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Completed {len(manifest['completed'])}/{len(shared['dates'])}; failed {len(manifest['failed'])}; {manifest_path}")
    return 1 if manifest["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

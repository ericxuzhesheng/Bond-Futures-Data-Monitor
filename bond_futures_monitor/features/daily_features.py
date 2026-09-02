"""Daily feature construction."""

from __future__ import annotations

import json
import sqlite3
from statistics import mean
from typing import Any

from bond_futures_monitor.ai.text_signal import sentiment_score


def build_daily_features(conn: sqlite3.Connection, run_date: str) -> dict[str, Any]:
    yields = {
        row["tenor"]: row["yield_value"]
        for row in conn.execute("SELECT tenor, yield_value FROM bond_yields WHERE date = ?", (run_date,))
    }
    funding = {
        row["rate_name"]: row["rate_value"]
        for row in conn.execute("SELECT rate_name, rate_value FROM funding_rates WHERE date = ?", (run_date,))
    }
    omo_rows = conn.execute(
        """
        SELECT operation_type, tenor_days, operation_amount, maturity_amount,
               net_injection_amount, operation_rate, data_source
        FROM open_market_operations
        WHERE date = ?
        """,
        (run_date,),
    ).fetchall()
    futures = conn.execute(
        "SELECT contract, daily_return, volume, open_interest, data_source FROM futures_quotes WHERE date = ?",
        (run_date,),
    ).fetchall()
    macro = {
        row["indicator"]: row["value"]
        for row in conn.execute("SELECT indicator, value FROM macro_indicators WHERE date = ?", (run_date,))
    }
    macro_sources = {
        row["data_source"]
        for row in conn.execute("SELECT DISTINCT data_source FROM macro_indicators WHERE date = ?", (run_date,))
    }
    yield_sources = {
        row["data_source"]
        for row in conn.execute("SELECT DISTINCT data_source FROM bond_yields WHERE date = ?", (run_date,))
    }
    funding_sources = {
        row["data_source"]
        for row in conn.execute("SELECT DISTINCT data_source FROM funding_rates WHERE date = ?", (run_date,))
    }
    news_sources = {
        row["data_source"]
        for row in conn.execute("SELECT DISTINCT data_source FROM policy_news WHERE date = ?", (run_date,))
    }
    omo_sources = {
        row["data_source"]
        for row in conn.execute("SELECT DISTINCT data_source FROM open_market_operations WHERE date = ?", (run_date,))
    }
    ai_rows = conn.execute(
        """
        SELECT signal.bond_impact
        FROM ai_text_signals AS signal
        JOIN (
            SELECT news_id, MAX(id) AS latest_id
            FROM ai_text_signals
            WHERE date = ?
            GROUP BY news_id
        ) AS latest
          ON latest.latest_id = signal.id
        ORDER BY signal.news_id
        """,
        (run_date,),
    ).fetchall()

    futures_returns = [row["daily_return"] for row in futures]
    volumes = {row["contract"]: row["volume"] for row in futures}
    ai_scores = [sentiment_score(row["bond_impact"]) for row in ai_rows]

    yield_10y_change = _yield_change(conn, run_date, "10Y")
    yield_30y_change = _yield_change(conn, run_date, "30Y")
    funding_anchor_name = "DR007" if "DR007" in funding else "FDR007" if "FDR007" in funding else None
    funding_anchor_change = (
        _rate_change(conn, run_date, funding_anchor_name) if funding_anchor_name is not None else None
    )
    broad_repo_name = "R007" if "R007" in funding else "FR007" if "FR007" in funding else None
    repo_7d_spread = (
        funding[broad_repo_name] - funding[funding_anchor_name]
        if broad_repo_name is not None and funding_anchor_name is not None
        else None
    )
    shibor_7d_spread = (
        funding["SHIBOR_7D"] - funding[funding_anchor_name]
        if "SHIBOR_7D" in funding and funding_anchor_name is not None
        else None
    )
    avg_volume_change = _avg_volume_change(conn, run_date, volumes)
    omo_net_injection_amount = sum(float(row["net_injection_amount"]) for row in omo_rows) if omo_rows else None
    operation_rates = [float(row["operation_rate"]) for row in omo_rows if row["operation_rate"] is not None]
    rolling_context = _rolling_context(conn, run_date, funding_anchor_name)
    return {
        "date": run_date,
        "yield_10y_change": yield_10y_change,
        "yield_30y_change": yield_30y_change,
        "spread_10y_2y": _spread(yields, "10Y", "2Y"),
        "spread_30y_10y": _spread(yields, "30Y", "10Y"),
        # Keep the database column name for compatibility; details below record
        # whether the value is based on DR007 or the distinct FDR007 fixing.
        "dr007_change": funding_anchor_change,
        "omo_net_injection_amount": omo_net_injection_amount,
        "omo_operation_rate": operation_rates[-1] if operation_rates else None,
        "avg_futures_return": mean(futures_returns) if futures_returns else None,
        "avg_volume_change": avg_volume_change,
        "avg_ai_sentiment_score": mean(ai_scores) if ai_scores else 0.0,
        "details": {
            "yield_curve": yields,
            "funding_rates": funding,
            "macro_indicators": macro,
            "futures_contract_count": len(futures),
            "ai_signal_count": len(ai_scores),
            "data_sources": {
                "futures": sorted({row["data_source"] for row in futures}),
                "yield_curve": sorted(yield_sources),
                "funding": sorted(funding_sources),
                "open_market_operations": sorted(omo_sources),
                "policy_news": sorted(news_sources),
                "macro": sorted(macro_sources),
            },
            "feature_groups": {
                "rates": {
                    "yield_10y_change": yield_10y_change,
                    "yield_30y_change": yield_30y_change,
                    "spread_10y_2y": _spread(yields, "10Y", "2Y"),
                    "spread_30y_10y": _spread(yields, "30Y", "10Y"),
                },
                "funding": {
                    "funding_anchor_name": funding_anchor_name,
                    "funding_anchor_value": funding.get(funding_anchor_name) if funding_anchor_name else None,
                    "funding_anchor_change": funding_anchor_change,
                    "repo_7d_spread": repo_7d_spread,
                    "shibor_7d_spread": shibor_7d_spread,
                    "available_rates": sorted(funding),
                },
                "open_market_operations": {
                    "omo_net_injection_amount": omo_net_injection_amount,
                    "omo_operation_rate": operation_rates[-1] if operation_rates else None,
                    "operation_count": len(omo_rows),
                },
                "futures": {
                    "avg_futures_return": mean(futures_returns) if futures_returns else None,
                    "avg_volume_change": avg_volume_change,
                    "contract_count": len(futures),
                },
                "text": {
                    "avg_ai_sentiment_score": mean(ai_scores) if ai_scores else 0.0,
                    "signal_count": len(ai_scores),
                },
                "macro": {
                    "lpr_1y": macro.get("LPR_1Y"),
                    "lpr_5y": macro.get("LPR_5Y"),
                    "cpi_yoy": macro.get("CPI_YOY"),
                    "ppi_yoy": macro.get("PPI_YOY"),
                    "pmi_mfg": macro.get("PMI_MFG"),
                    "indicator_count": len(macro),
                },
            },
            "rolling_context": rolling_context,
        },
    }


def feature_from_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["details"] = json.loads(data.pop("details_json"))
    return data


def _spread(values: dict[str, float], long_tenor: str, short_tenor: str) -> float | None:
    if long_tenor not in values or short_tenor not in values:
        return None
    return values[long_tenor] - values[short_tenor]


def _yield_change(conn: sqlite3.Connection, run_date: str, tenor: str) -> float | None:
    today = conn.execute(
        "SELECT yield_value FROM bond_yields WHERE date = ? AND tenor = ?",
        (run_date, tenor),
    ).fetchone()
    if not today:
        return None
    prior = conn.execute(
        "SELECT yield_value FROM bond_yields WHERE date < ? AND tenor = ? ORDER BY date DESC LIMIT 1",
        (run_date, tenor),
    ).fetchone()
    if not prior:
        return None
    return today["yield_value"] - prior["yield_value"]


def _rate_change(conn: sqlite3.Connection, run_date: str, rate_name: str) -> float | None:
    today = conn.execute(
        "SELECT rate_value FROM funding_rates WHERE date = ? AND rate_name = ?",
        (run_date, rate_name),
    ).fetchone()
    if not today:
        return None
    prior = conn.execute(
        "SELECT rate_value FROM funding_rates WHERE date < ? AND rate_name = ? ORDER BY date DESC LIMIT 1",
        (run_date, rate_name),
    ).fetchone()
    if not prior:
        return None
    return today["rate_value"] - prior["rate_value"]


def _avg_volume_change(
    conn: sqlite3.Connection,
    run_date: str,
    today_volumes: dict[str, float],
) -> float | None:
    if not today_volumes:
        return None
    prior_date_row = conn.execute(
        "SELECT MAX(date) AS d FROM futures_quotes WHERE date < ?",
        (run_date,),
    ).fetchone()
    if not prior_date_row or not prior_date_row["d"]:
        return None
    prior_volumes = {
        row["contract"]: row["volume"]
        for row in conn.execute(
            "SELECT contract, volume FROM futures_quotes WHERE date = ?",
            (prior_date_row["d"],),
        )
    }
    pct_changes = [
        (vol - prior_volumes[contract]) / prior_volumes[contract]
        for contract, vol in today_volumes.items()
        if contract in prior_volumes and prior_volumes[contract] > 0
    ]
    return mean(pct_changes) if pct_changes else None


def _rolling_context(conn: sqlite3.Connection, run_date: str, funding_anchor: str | None) -> dict[str, Any]:
    """Build point-in-time rolling diagnostics using only observations available by run_date."""

    yield_rows = conn.execute(
        "SELECT date, yield_value FROM bond_yields WHERE tenor='10Y' AND date <= ? ORDER BY date DESC LIMIT 61",
        (run_date,),
    ).fetchall()[::-1]
    yield_changes = [
        float(yield_rows[index]["yield_value"]) - float(yield_rows[index - 1]["yield_value"])
        for index in range(1, len(yield_rows))
    ]
    funding_changes: list[float] = []
    if funding_anchor:
        rows = conn.execute(
            "SELECT date, rate_value FROM funding_rates WHERE rate_name=? AND date <= ? ORDER BY date DESC LIMIT 61",
            (funding_anchor, run_date),
        ).fetchall()[::-1]
        funding_changes = [
            float(rows[index]["rate_value"]) - float(rows[index - 1]["rate_value"])
            for index in range(1, len(rows))
        ]

    futures_rows = conn.execute(
        """
        SELECT date, AVG(daily_return) AS avg_return, SUM(volume) AS volume,
               SUM(open_interest) AS open_interest
        FROM futures_quotes WHERE date <= ? GROUP BY date ORDER BY date DESC LIMIT 20
        """,
        (run_date,),
    ).fetchall()[::-1]
    current = futures_rows[-1] if futures_rows else None
    history = futures_rows[:-1]
    avg_volume_20d = mean(float(row["volume"]) for row in history) if history else None
    avg_oi_20d = mean(float(row["open_interest"]) for row in history) if history else None
    current_return = float(current["avg_return"]) if current else None
    previous_oi = float(history[-1]["open_interest"]) if history else None
    current_oi = float(current["open_interest"]) if current else None
    oi_change = (
        (current_oi - previous_oi) / previous_oi
        if current_oi is not None and previous_oi not in (None, 0)
        else None
    )
    return {
        "history_days": len(futures_rows),
        "yield_10y_change_percentile_60d": _percentile_rank(yield_changes),
        "funding_change_percentile_60d": _percentile_rank(funding_changes),
        "futures_return_percentile_20d": _percentile_rank([float(row["avg_return"]) for row in futures_rows]),
        "volume_ratio_20d": float(current["volume"]) / avg_volume_20d if current and avg_volume_20d else None,
        "open_interest_ratio_20d": current_oi / avg_oi_20d if current_oi is not None and avg_oi_20d else None,
        "open_interest_change_1d": oi_change,
        "price_oi_quadrant": _price_oi_quadrant(current_return, oi_change),
    }


def _percentile_rank(values: list[float]) -> float | None:
    if len(values) < 5:
        return None
    current = values[-1]
    return sum(value <= current for value in values) / len(values)


def _price_oi_quadrant(price_return: float | None, oi_change: float | None) -> str:
    if price_return is None or oi_change is None:
        return "数据不足"
    if price_return >= 0 and oi_change >= 0:
        return "价涨增仓"
    if price_return >= 0 and oi_change < 0:
        return "价涨减仓"
    if price_return < 0 and oi_change >= 0:
        return "价跌增仓"
    return "价跌减仓"

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
    futures = conn.execute(
        "SELECT contract, daily_return, volume, data_source FROM futures_quotes WHERE date = ?",
        (run_date,),
    ).fetchall()
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
    ai_rows = conn.execute("SELECT bond_impact FROM ai_text_signals WHERE date = ?", (run_date,)).fetchall()

    futures_returns = [row["daily_return"] for row in futures]
    volumes = {row["contract"]: row["volume"] for row in futures}
    ai_scores = [sentiment_score(row["bond_impact"]) for row in ai_rows]

    yield_10y_change = _yield_change(conn, run_date, "10Y")
    yield_30y_change = _yield_change(conn, run_date, "30Y")
    dr007_change = _rate_change(conn, run_date, "DR007")
    avg_volume_change = _avg_volume_change(conn, run_date, volumes)

    return {
        "date": run_date,
        "yield_10y_change": yield_10y_change,
        "yield_30y_change": yield_30y_change,
        "spread_10y_2y": _spread(yields, "10Y", "2Y"),
        "spread_30y_10y": _spread(yields, "30Y", "10Y"),
        "dr007_change": dr007_change,
        "avg_futures_return": mean(futures_returns) if futures_returns else None,
        "avg_volume_change": avg_volume_change,
        "avg_ai_sentiment_score": mean(ai_scores) if ai_scores else 0.0,
        "details": {
            "yield_curve": yields,
            "funding_rates": funding,
            "futures_contract_count": len(futures),
            "ai_signal_count": len(ai_scores),
            "data_sources": {
                "futures": sorted({row["data_source"] for row in futures}),
                "yield_curve": sorted(yield_sources),
                "funding": sorted(funding_sources),
                "policy_news": sorted(news_sources),
            },
            "feature_groups": {
                "rates": {
                    "yield_10y_change": yield_10y_change,
                    "yield_30y_change": yield_30y_change,
                    "spread_10y_2y": _spread(yields, "10Y", "2Y"),
                    "spread_30y_10y": _spread(yields, "30Y", "10Y"),
                },
                "funding": {
                    "dr007_change": dr007_change,
                    "available_rates": sorted(funding),
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
            },
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

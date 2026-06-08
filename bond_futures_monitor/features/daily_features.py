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
    volumes = [row["volume"] for row in futures]
    ai_scores = [sentiment_score(row["bond_impact"]) for row in ai_rows]

    # Sample fallback approximates prior-day changes until historical collectors are added.
    yield_10y_change = -0.015 if "10Y" in yields else None
    yield_30y_change = -0.012 if "30Y" in yields else None
    dr007_change = -0.05 if "DR007" in funding else None

    return {
        "date": run_date,
        "yield_10y_change": yield_10y_change,
        "yield_30y_change": yield_30y_change,
        "spread_10y_2y": _spread(yields, "10Y", "2Y"),
        "spread_30y_10y": _spread(yields, "30Y", "10Y"),
        "dr007_change": dr007_change,
        "avg_futures_return": mean(futures_returns) if futures_returns else None,
        "avg_volume_change": 0.08 if volumes else None,
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
                    "avg_volume_change": 0.08 if volumes else None,
                    "contract_count": len(futures),
                },
                "text": {
                    "avg_ai_sentiment_score": mean(ai_scores) if ai_scores else 0.0,
                    "signal_count": len(ai_scores),
                },
            },
            "note": "Change features use sample prior-day approximations in MVP fallback mode.",
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

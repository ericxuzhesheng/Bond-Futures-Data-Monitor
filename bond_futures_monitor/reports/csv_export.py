"""Cumulative daily-features CSV export.

Regenerates ``daily_features.csv`` in full from the database on every run so
the file always mirrors the ``daily_features`` and ``daily_market_signals``
tables — append-only bookkeeping and dedup logic are unnecessary, and a rerun
for one date is naturally idempotent.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path


# Stable English column names for the per-dimension score categories emitted
# by the rule-based signal (signals/rule_based.py).
SCORE_CATEGORY_COLUMNS = {
    "利率方向": "score_rate_direction",
    "曲线形态": "score_curve_shape",
    "资金面": "score_funding",
    "公开市场操作": "score_omo",
    "期货量价": "score_futures_volume_price",
    "文本信号": "score_text_signal",
    "宏观基本面": "score_macro",
}

FEATURE_COLUMNS = (
    "yield_10y_change",
    "yield_30y_change",
    "spread_10y_2y",
    "spread_30y_10y",
    "dr007_change",
    "omo_net_injection_amount",
    "avg_futures_return",
    "avg_volume_change",
    "avg_ai_sentiment_score",
)

CSV_FILENAME = "daily_features.csv"


def export_features_csv(conn: sqlite3.Connection, output_dir: Path) -> Path:
    """Write the cumulative feature/signal time series as one CSV row per date."""

    output_dir.mkdir(parents=True, exist_ok=True)
    header = (
        ["date"]
        + list(FEATURE_COLUMNS)
        + list(SCORE_CATEGORY_COLUMNS.values())
        + ["total_score", "market_view"]
    )

    rows = conn.execute(
        """
        SELECT f.date, f.yield_10y_change, f.yield_30y_change, f.spread_10y_2y,
               f.spread_30y_10y, f.dr007_change, f.omo_net_injection_amount,
               f.avg_futures_return, f.avg_volume_change, f.avg_ai_sentiment_score,
               s.total_score, s.market_view, s.details_json AS signal_details_json
        FROM daily_features AS f
        LEFT JOIN daily_market_signals AS s ON s.date = f.date
        ORDER BY f.date
        """
    ).fetchall()

    path = output_dir / CSV_FILENAME
    # utf-8-sig so Excel (the most common consumer) renders Chinese values correctly.
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(
                [row["date"]]
                + [row[column] for column in FEATURE_COLUMNS]
                + _score_values(row["signal_details_json"])
                + [row["total_score"], row["market_view"]]
            )
    return path


def _score_values(details_json: str | None) -> list[float | None]:
    """Flatten per-dimension score items into the stable column order."""

    scores: dict[str, float] = {}
    if details_json:
        try:
            items = json.loads(details_json).get("score_items", [])
        except (json.JSONDecodeError, AttributeError):
            items = []
        for item in items:
            column = SCORE_CATEGORY_COLUMNS.get(str(item.get("category", "")))
            if column is not None and isinstance(item.get("score"), (int, float)):
                scores[column] = float(item["score"])
    return [scores.get(column) for column in SCORE_CATEGORY_COLUMNS.values()]
